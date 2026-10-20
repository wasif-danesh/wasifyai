// Wasify AI, Video Builder: the exact-text check (ADR-0079 decision 7).
// Opens a composition in the sandboxed browser, seeks the timeline to the moments the template names, and reports
// what is really drawn for each element marked data-slot: its text, whether it is visible, whether ink is painted,
// whether anything is cut off by a clip, and whether it is inside the title-safe margin. It decides nothing: the
// product compares the report with what the person typed.
//   node check.mjs <spec.json>   where spec = {project, width, height, transparent, safe, items:[{slot, at}]}
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import puppeteer from "puppeteer-core";
import sharp from "sharp";

const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const root = path.resolve(spec.project);
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".woff2": "font/woff2",
  ".json": "application/json",
};

const server = http.createServer((req, res) => {
  try {
    let rel = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (rel === "/") rel = "/index.html";
    const file = path.resolve(root, `.${rel}`);
    if (!file.startsWith(root + path.sep)) {
      res.writeHead(403);
      return res.end();
    }
    const data = fs.readFileSync(file);
    res.writeHead(200, { "content-type": MIME[path.extname(file)] ?? "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;

async function crop(png, box) {
  return sharp(png).extract(box).ensureAlpha().raw().toBuffer();
}

function differing(a, b) {
  let n = 0;
  for (let i = 0; i < a.length; i += 4) {
    const d = Math.max(
      Math.abs(a[i] - b[i]),
      Math.abs(a[i + 1] - b[i + 1]),
      Math.abs(a[i + 2] - b[i + 2]),
      Math.abs(a[i + 3] - b[i + 3]),
    );
    if (d > 40) n += 1;
  }
  return n;
}

let browser;
try {
  browser = await puppeteer.launch({
    executablePath: process.env.HYPERFRAMES_BROWSER_PATH,
    headless: "shell",
    defaultViewport: { width: spec.width, height: spec.height, deviceScaleFactor: 1 },
    args: [],
  });
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.log(`NOTE PAGEERROR ${e.message}`));
  page.on("requestfailed", (r) => console.log(`NOTE REQUESTFAILED ${r.url()}`));
  page.on("response", (r) => r.status() >= 400 && console.log(`NOTE HTTP ${r.status()} ${r.url()}`));
  await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => Boolean(window.__timelines?.main), { polling: 100, timeout: 10000 });
  const fonts = await page.evaluate(() => [...document.fonts].map((f) => `${f.family}:${f.status}`));
  const items = [];
  const moments = [...new Set(spec.items.map((i) => i.at))].sort((a, b) => a - b);
  const margin = Math.round(spec.safe * spec.width);
  for (const at of moments) {
    await page.evaluate((t) => {
      window.__timelines.main.pause();
      window.__timelines.main.seek(t, false);
    }, at);
    const opts = { type: "png", omitBackground: Boolean(spec.transparent) };
    const base = await page.screenshot(opts);
    await page.evaluate(() => {
      const s = document.createElement("style");
      s.id = "vb-noclip";
      s.textContent =
        "*:not(html):not(body){overflow:visible !important;clip-path:none !important;mask:none !important;-webkit-mask:none !important}";
      document.head.appendChild(s);
    });
    const free = await page.screenshot(opts);
    await page.evaluate(() => document.getElementById("vb-noclip")?.remove());
    for (const item of spec.items.filter((i) => i.at === at)) {
      const info = await page.evaluate((slot) => {
        const el = document.querySelector(`[data-slot="${slot}"]`);
        if (!el) return null;
        // the box of the letters themselves, not of the block that holds them
        const range = document.createRange();
        range.selectNodeContents(el);
        const r = range.getBoundingClientRect();
        let opacity = 1;
        let shown = true;
        for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
          const c = getComputedStyle(n);
          opacity *= Number.parseFloat(c.opacity);
          if (c.display === "none" || c.visibility === "hidden") shown = false;
        }
        return { text: el.innerText, x: r.x, y: r.y, w: r.width, h: r.height, opacity, shown };
      }, item.slot);
      if (!info) {
        items.push({ slot: item.slot, at, found: false });
        continue;
      }
      const pad = 6;
      const x = Math.max(0, Math.floor(info.x - pad));
      const y = Math.max(0, Math.floor(info.y - pad));
      const w = Math.min(spec.width - x, Math.ceil(info.w + 2 * pad));
      const h = Math.min(spec.height - y, Math.ceil(info.h + 2 * pad));
      let inked = 0;
      let clipped = 0;
      if (w > 0 && h > 0) {
        const box = { left: x, top: y, width: w, height: h };
        // hide the element: how many pixels change is how much of it is really drawn
        await page.evaluate((slot) => {
          document.querySelector(`[data-slot="${slot}"]`).style.visibility = "hidden";
        }, item.slot);
        const hidden = await page.screenshot(opts);
        await page.evaluate((slot) => {
          document.querySelector(`[data-slot="${slot}"]`).style.visibility = "";
        }, item.slot);
        inked = differing(await crop(base, box), await crop(hidden, box));
        // with every clip removed: if the picture around it changes, something was cut off
        clipped = differing(await crop(base, box), await crop(free, box));
      }
      items.push({
        slot: item.slot,
        at,
        found: true,
        text: info.text,
        shown: info.shown,
        opacity: info.opacity,
        inked,
        clipped,
        inside:
          info.x >= margin - 1 &&
          info.y >= margin - 1 &&
          info.x + info.w <= spec.width - margin + 1 &&
          info.y + info.h <= spec.height - margin + 1,
      });
    }
  }
  console.log(`RESULT ${JSON.stringify({ items, fonts })}`);
} catch (e) {
  console.log(`ERROR ${String(e?.message ?? e).slice(0, 300)}`);
  process.exitCode = 1;
} finally {
  await browser?.close().catch(() => {});
  server.close();
}
