// Pictures of the real desktop window for the UI audit (docs/ui-audit-2026-10-27.md), written to
// docs/ui-audit/desktop/. Run by ui-audit.sh, which starts the engine and the window's dev server and
// passes WASIFYAI_AUDIT_BASE and WASIFYAI_AUDIT_TOKEN. The Tauri shell is not running: the polyfill below
// answers the window's few shell commands (engine_status, engine_session, update_check, ...).
//
//   apps/desktop/scripts/ui-audit.sh            light and dark
//   apps/desktop/scripts/ui-audit.sh light      one scheme
//   apps/desktop/scripts/ui-audit.sh light home,image-create   only these screens
//   apps/desktop/scripts/ui-audit.sh light image-make           a real picture, made in the window (pictures of
//                                                                the stage while it is made and when it is done)
//   apps/desktop/scripts/ui-audit.sh light video-make           a real clip from the newest picture: Animate this on
//                                                                Images, the clip made on the stage, then Extend this
//   apps/desktop/scripts/ui-audit.sh light speech-make          a real speech with its waveform, then a real transcript
//                                                                of it on Speech to text
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
const names = new Set((process.argv[3] ?? "").split(",").filter(Boolean));
const wanted = (name) => names.size === 0 || names.has(name);
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
    if (!wanted(name)) continue;
    if (scheme === "dark" && !DARK.has(name)) continue;
    await attempt(name, async () => {
      await open(page, path);
      await shot(page, name + suffix);
      if (scheme === "light" && TALL.has(name)) await shot(page, `${name}-tall`, 2000);
    });
  }
  if (scheme === "light" && names.has("image-make")) {
    // the check of stage U3: a real picture made in the window, the stage pictured while it works and when it is done
    await attempt("image-make", async () => {
      await open(page, "/images/create");
      await page
        .getByRole("textbox", { name: /prompt/i })
        .fill("A red ceramic teapot on a wooden table, soft morning light");
      await page.getByRole("button", { name: "Make the picture" }).click();
      await page.locator('[data-slot="stage"][data-state="working"]').waitFor({ timeout: 20_000 });
      await page.waitForTimeout(1500);
      await shot(page, "image-making");
      await page
        .locator('[data-slot="stage"][data-state="result"] img')
        .waitFor({ timeout: 300_000 });
      await page.waitForTimeout(800);
      await shot(page, "image-made");
      await page.getByRole("button", { name: "More" }).click();
      await page.waitForTimeout(400);
      await shot(page, "image-made-more");
      await page.keyboard.press("Escape");
    });
  }
  if (scheme === "light" && names.has("video-make")) {
    // the check of stage U4: Animate this hands the newest picture to Video, a real clip is made on the stage,
    // and Extend this opens Extend with it chosen
    await attempt("video-make", async () => {
      await open(page, "/images/create");
      await page.locator('[data-slot="recent-strip"] button[aria-label^="Open:"]').first().click();
      await page.getByRole("button", { name: "Animate this" }).click();
      await page.getByText("Animate a picture").first().waitFor();
      await page.waitForTimeout(3000); // the picture is fetched and uploaded
      await shot(page, "video-animate-handed");
      await page
        .getByRole("textbox", { name: /what should move/i })
        .fill("Steam rises slowly from the cup and the camera gently pushes in");
      await page.getByRole("button", { name: "Make the video" }).click();
      await page.locator('[data-slot="stage"][data-state="working"]').waitFor({ timeout: 20_000 });
      await page.waitForTimeout(20_000);
      await shot(page, "video-making");
      await page
        .locator('[data-slot="stage"][data-state="result"] video')
        .waitFor({ timeout: 1_800_000 });
      await page.waitForTimeout(1500);
      await shot(page, "video-made");
      await page.getByRole("button", { name: "More" }).click();
      await page.waitForTimeout(400);
      await shot(page, "video-made-more");
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "Extend this" }).click();
      await page.getByText("Extend a video").first().waitFor();
      await page.waitForTimeout(1500);
      await shot(page, "video-extend-chosen");
    });
  }
  if (scheme === "light" && names.has("speech-make")) {
    // the check of stage U5: a real speech on the stage with its waveform, then that speech transcribed
    await attempt("speech-make", async () => {
      await open(page, "/voice/speak");
      await page.getByLabel("What should it say?").waitFor({ timeout: 60_000 });
      await shot(page, "speech-voices");
      await page
        .getByLabel("What should it say?")
        .fill("Good morning. This is the new speech screen, made on this computer.");
      await page.getByRole("button", { name: "Make the speech" }).click();
      await page
        .locator('[data-slot="stage"][data-state="result"] [data-slot="player"]')
        .waitFor({ timeout: 300_000 });
      await page.waitForTimeout(2500); // the waveform is read
      await shot(page, "speech-made");
      const src = await page.locator('[data-slot="stage"] audio').getAttribute("src");
      const b64 = await page.evaluate(async (url) => {
        const bytes = new Uint8Array(await (await fetch(url)).arrayBuffer());
        let bin = "";
        for (const b of bytes) bin += String.fromCharCode(b);
        return btoa(bin);
      }, src);
      await page.getByRole("button", { name: "Make a voice" }).click();
      await page.waitForTimeout(800);
      await shot(page, "speech-make-a-voice");
      await page.keyboard.press("Escape");
      await open(page, "/voice/transcribe");
      await page.getByLabel("Choose a recording").setInputFiles({
        name: "good-morning.wav",
        mimeType: "audio/wav",
        buffer: Buffer.from(b64, "base64"),
      });
      await page.getByRole("button", { name: "Transcribe" }).click();
      await page.getByRole("article", { name: "Transcript" }).waitFor({ timeout: 300_000 });
      await page.waitForTimeout(800);
      await shot(page, "transcript-made");
    });
  }
  if (scheme === "light" && names.size === 0) {
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
    await attempt("search", async () => {
      await open(page, "/images/create");
      await page.keyboard.press("Meta+K");
      await page.waitForTimeout(500);
      await shot(page, "search");
      await page.keyboard.press("Escape");
    });
    await attempt("tray", async () => {
      await open(page, "/images/create");
      await page.getByRole("button", { name: /running|Nothing running/ }).click();
      await page.waitForTimeout(500);
      await shot(page, "tray");
      await page.keyboard.press("Escape");
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
