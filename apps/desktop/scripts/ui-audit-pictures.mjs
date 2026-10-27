// Pictures of the real desktop window for the UI audit (docs/ui-audit-2026-10-27.md), written to
// docs/ui-audit/desktop/. Run by ui-audit.sh, which starts the engine and the window's dev server and
// passes WASIFYAI_AUDIT_BASE and WASIFYAI_AUDIT_TOKEN. The Tauri shell is not running: the polyfill below
// answers the window's few shell commands (engine_status, engine_session, update_check, ...).
//
//   apps/desktop/scripts/ui-audit.sh            light and dark
//   apps/desktop/scripts/ui-audit.sh light      one scheme
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const require = createRequire(join(ROOT, "apps", "web", "package.json"));
const { chromium } = require("@playwright/test");
const OUT = join(ROOT, "docs", "ui-audit", "desktop");
const BASE = process.env.WASIFYAI_AUDIT_BASE ?? "http://127.0.0.1:8765";
const TOKEN = process.env.WASIFYAI_AUDIT_TOKEN ?? "";
const WINDOW = "http://localhost:1420";
const only = process.argv[2] ?? "";
mkdirSync(OUT, { recursive: true });

const polyfill = `
window.__TAURI_INTERNALS__ = {
  transformCallback(cb) { const id = Math.floor(Math.random() * 1e9); window["_" + id] = cb; return id; },
  unregisterCallback() {},
  convertFileSrc(p) { return p; },
  async invoke(cmd) {
    switch (cmd) {
      case "engine_status": return { state: "ready", base_url: ${JSON.stringify(BASE)}, pid: 1 };
      case "engine_session": return { base_url: ${JSON.stringify(BASE)}, token: ${JSON.stringify(TOKEN)}, expires_at: ${Math.floor(Date.now() / 1000) + 3600} };
      case "smoke_enabled": return false;
      case "smoke_component": return null;
      case "update_check": return { state: "not_configured" };
      case "component_status": return { state: "installed", version: "", accelerator: "mps" };
      case "plugin:event|listen": return 1;
      default: return null;
    }
  },
};
window.isTauri = true;
`;

async function engine(path) {
  const res = await fetch(`${BASE}${path}`, { headers: { authorization: `Bearer ${TOKEN}` } });
  return res.ok ? res.json() : null;
}
// a saved notebook and a saved chat, so the pictures show real content
const notebooks = (await engine("/products/wasifyai-notebooks/notebooks")) ?? [];
const chats =
  (await engine("/products/wasifyai-assistant/conversations?limit=1"))?.conversations ?? [];
const NOTEBOOK = notebooks[0]?.id;
const CHAT = chats[0]?.id;

const SCREENS = [
  ["home", "/"],
  ["chat-saved", CHAT ? `/chat/${CHAT}` : null],
  ["image-create", "/images/create"],
  ["image-edit", "/images/edit"],
  ["image-inpaint", "/images/inpaint"],
  ["image-reference", "/images/reference"],
  ["image-library", "/library"],
  ["image-3d", "/images/3d"],
  ["video-create", "/video/create"],
  ["video-animate", "/video/animate"],
  ["video-extend", "/video/extend"],
  ["video-builder", "/video/builder"],
  ["video-library", "/video/library"],
  ["voice-speak", "/voice/speak"],
  ["voice-transcribe", "/voice/transcribe"],
  ["voice-voices", "/voice/voices"],
  ["voice-convert", "/voice/convert"],
  ["voice-edit", "/voice/edit-speech"],
  ["voice-dub", "/voice/dub"],
  ["voice-audiobook", "/voice/audiobook"],
  ["voice-lipsync", "/voice/lip-sync"],
  ["music-create", "/music/create"],
  ["music-tracks", "/music/library"],
  ["music-lyrics", "/music/lyrics"],
  ["music-separate", "/music/separate"],
  ["notebooks", "/notebooks"],
  ["notebook", NOTEBOOK ? `/notebooks/${NOTEBOOK}` : null],
  ["notebook-new", "/notebooks/new"],
  ["creations", "/creations"],
  ["train", "/train"],
  ["models", "/models"],
  ["settings", "/settings"],
].filter(([, path]) => path);
// screens longer than a window: a second picture in a tall window shows the whole of them
const TALL = new Set([
  "settings",
  "models",
  "train",
  "voice-lipsync",
  "voice-dub",
  "voice-audiobook",
  "creations",
  "image-3d",
  "video-builder",
  "music-create",
  "notebooks",
]);
const DARK = new Set([
  "home",
  "image-create",
  "video-create",
  "voice-speak",
  "music-create",
  "notebook",
  "creations",
  "train",
  "models",
  "settings",
]);

async function open(page, path) {
  await page.goto(`${WINDOW}/#${path}`);
  await page.locator("#main").waitFor();
  await page.waitForTimeout(2500);
}
async function shot(page, name, height = 900) {
  if (height !== 900) {
    await page.setViewportSize({ width: 1440, height });
    await page.waitForTimeout(400);
  }
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  if (height !== 900) await page.setViewportSize({ width: 1440, height: 900 });
  console.log("wrote", name);
}
async function attempt(name, fn) {
  try {
    await fn();
  } catch (e) {
    console.log("failed", name, e instanceof Error ? e.message.split("\n")[0] : e);
  }
}

const browser = await chromium.launch();
for (const scheme of ["light", "dark"]) {
  if (only && only !== scheme) continue;
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: scheme,
  });
  await ctx.addInitScript(polyfill);
  await ctx.addInitScript(() => {
    try {
      localStorage.setItem("wasifyai:sidebar-collapsed", "0");
    } catch {}
  });
  const page = await ctx.newPage();
  const suffix = scheme === "dark" ? "-dark" : "";
  for (const [name, path] of SCREENS) {
    if (scheme === "dark" && !DARK.has(name)) continue;
    await attempt(name, async () => {
      await open(page, path);
      await shot(page, name + suffix);
      if (scheme === "light" && TALL.has(name)) await shot(page, `${name}-tall`, 2000);
    });
  }
  if (scheme === "light") {
    for (const [name, path] of [
      ["picker-images", "/images/create"],
      ["picker-speech", "/voice/speak"],
      ["picker-chat", "/"],
    ]) {
      await attempt(name, async () => {
        await open(page, path);
        await page.locator('button[aria-haspopup="dialog"]').first().click();
        await page.waitForTimeout(1200);
        await shot(page, name);
        await page.keyboard.press("Escape");
      });
    }
    await attempt("menu-hidden", async () => {
      await open(page, "/images/create");
      await page.getByRole("button", { name: "Hide the side menu" }).click();
      await page.waitForTimeout(500);
      await shot(page, "menu-hidden");
      await page.getByRole("button", { name: "Show the side menu" }).click();
    });
    await attempt("menu-open", async () => {
      await open(page, "/images/create");
      const nav = page.locator("nav").first();
      for (const group of ["Notebook", "Images", "Video", "Voice", "Music"]) {
        const button = nav.getByRole("button", { name: group, exact: true });
        if ((await button.getAttribute("aria-expanded")) !== "true") await button.click();
        await page.waitForTimeout(150);
      }
      await shot(page, "menu-open", 1500);
    });
    await attempt("search-sidebar", async () => {
      await open(page, "/");
      await page.getByRole("button", { name: "Search My creations" }).click();
      await page.waitForTimeout(1500);
      await shot(page, "search-sidebar");
    });
    // Train: the next screen of each card whose Start works (the video card waits for its trainer)
    for (const [i, name] of [
      [0, "train-pictures"],
      [1, "train-writing"],
      [2, "train-decide"],
    ]) {
      await attempt(name, async () => {
        await open(page, "/train");
        await page
          .locator('section[aria-label="What to teach"] > *')
          .nth(i)
          .locator("button")
          .first()
          .click();
        await page.waitForTimeout(2500);
        await shot(page, name, 1400);
      });
    }
    await attempt("models-advanced", async () => {
      await open(page, "/models");
      await page.locator("summary", { hasText: "Advanced" }).click();
      await page.waitForTimeout(2000);
      await shot(page, "models-advanced", 3200);
    });
  }
  await ctx.close();
}
await browser.close();
