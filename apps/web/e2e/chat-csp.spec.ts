import { execFileSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { type Server, createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { extname, join, normalize, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { TRACKER } from "../../../packages/ui/src/chat/thread/markdown/adversarial";

// The new chat under the desktop window's real content-security policy (apps/desktop/src-tauri/tauri.conf.json), in Chromium: the
// chat is built on its own (packages/ui/bundle) and served with that policy as a header. Highlighting, maths and diagrams must work
// with no violation of the policy, no `unsafe-eval` and no remote font, and a hostile answer must still do nothing. WebKit (the
// real window) is checked by hand: docs/chat-ui-migration-plan.md, "CU1 as built".

const REPO = resolve(__dirname, "../../..");
const CSP: string = JSON.parse(
  readFileSync(join(REPO, "apps/desktop/src-tauri/tauri.conf.json"), "utf8"),
).app.security.csp;

const TYPES: Record<string, string> = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".ttf": "font/ttf",
  ".json": "application/json",
  ".svg": "image/svg+xml",
};

let dir = "";
let server: Server;
let base = "";

test.beforeAll(async () => {
  dir = mkdtempSync(join(tmpdir(), "chat-csp-"));
  execFileSync(
    "node",
    [
      "-e",
      `import("${join(REPO, "scripts/chat/harness.mjs")}").then((m) => m.buildHarness(${JSON.stringify(dir)}, "csp.html"))`,
    ],
    { stdio: "inherit" },
  );
  server = createServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    const file = normalize(join(dir, path === "/" ? "csp.html" : path));
    if (!file.startsWith(dir)) return void res.writeHead(403).end();
    try {
      const body = readFileSync(file);
      res.writeHead(200, {
        "content-type": TYPES[extname(file)] ?? "application/octet-stream",
        "content-security-policy": CSP,
      });
      res.end(body);
    } catch {
      res.writeHead(404).end();
    }
  });
  await new Promise<void>((ok) => server.listen(0, "127.0.0.1", ok));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

test.afterAll(async () => {
  await new Promise((ok) => server.close(ok));
  rmSync(dir, { recursive: true, force: true });
});

async function open(page: import("@playwright/test").Page, query: string) {
  const outside: string[] = [];
  const hits: string[] = [];
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      (window as unknown as { __csp: string[] }).__csp ??= [];
      (window as unknown as { __csp: string[] }).__csp.push(
        `${e.violatedDirective} ${e.blockedURI}`,
      );
    });
  });
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (r.url().startsWith(TRACKER)) hits.push(r.url());
    if (!["data:", "blob:"].includes(u.protocol) && !r.url().startsWith(base))
      outside.push(r.url());
  });
  await page.route(`${TRACKER}/**`, (route) => route.abort());
  await page.goto(`${base}/?${query}`);
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("go");
  await box.press("Enter");
  return {
    outside,
    hits,
    flags: () => page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? []),
  };
}

test("the chat runs under the window's policy: code, maths and a diagram, no violation, no request that leaves @layout", async ({
  page,
}, info) => {
  test.skip(info.project.name !== "desktop-light", "one browser is enough for this check");
  const seen = await open(page, "");
  await expect(page.locator("[data-streamdown='code-block'] span span").first()).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.locator(".katex").first()).toBeVisible({ timeout: 15_000 });
  await expect(
    page.locator("[data-streamdown='mermaid'] svg, svg[id^='mermaid']").first(),
  ).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(500);
  expect(await seen.flags(), "the policy blocked something the chat needs").toEqual([]);
  expect(seen.outside, "a request left the page").toEqual([]);
  expect(CSP).not.toMatch(/unsafe-eval|wasm-unsafe-eval/);
  // and the policy really is in force on this page: an inline script does not run
  const ran = await page.evaluate(() => {
    const el = document.createElement("script");
    el.textContent = "window.__inline = 1";
    document.head.appendChild(el);
    return (window as unknown as { __inline?: number }).__inline === 1;
  });
  expect(ran, "the policy is not applied to the test page").toBe(false);
});

test("a hostile answer does nothing under the window's policy, and the loopback address is not asked for a picture @layout", async ({
  page,
}, info) => {
  test.skip(info.project.name !== "desktop-light", "one browser is enough for this check");
  const seen = await open(page, "hostile=1");
  await expect(page.locator("[data-markdown]").first()).toBeVisible();
  await expect(page.locator(".katex").first()).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(1500);
  // the policy allows any 127.0.0.1 port for pictures, so only the renderer stands between a model and a local service
  expect(seen.hits, "a picture was requested from the loopback tracker").toEqual([]);
  const flags = await page.evaluate(() =>
    Object.keys(window).filter((k) => k.startsWith("__pwned")),
  );
  expect(flags).toEqual([]);
  await expect(page.locator("[data-markdown] foreignObject")).toHaveCount(0);
});
