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
//   apps/desktop/scripts/ui-audit.sh light studio-make          a real dub of the newest speech (into English, or
//                                                                WASIFYAI_AUDIT_DUB_LANGUAGE) (the
//                                                                script, the voice, the dub), then a real portrait
//                                                                made on Images and turned into a lip sync video
//   apps/desktop/scripts/ui-audit.sh light music-make           a real instrumental on Create music, its More menu,
//                                                                then Split into parts with it chosen
//   apps/desktop/scripts/ui-audit.sh light library-make         the Library: a picture opened, Edit this, a real
//                                                                edit made, then "Made from" and "Made from this"
//   apps/desktop/scripts/ui-audit.sh light a11y                 every screen of the window against the accessibility
//                                                                rules (axe, WCAG 2.2 A and AA); prints what fails
//   apps/desktop/scripts/ui-audit.sh light u11-make             Settings (what this computer can do, the groups, a
//                                                                search, the theme, a setting saved as it changes),
//                                                                the Models page and the picker with their dots
//   apps/desktop/scripts/ui-audit.sh light u10-make             Teach's front door, a real notebook report as a card,
//                                                                a real Motion graphics video on the frame, and a real
//                                                                3D picture check (its cut-out) on the stage
//   apps/desktop/scripts/ui-audit.sh light motion-editor        The Motion graphics editor (ADR-0096 MX2): a new project,
//                                                                edits, playback, Undo, axe, a phone width and a real
//                                                                video; use a throwaway DESKTOP_DATA_DIR
//   apps/desktop/scripts/ui-audit.sh light styles-make          Styles (ADR-0091 S2): the section, the Add menu, Train's
//                                                                style chosen and a real picture made with it, then
//                                                                the section on Edit, Inpaint and Reference
//   apps/desktop/scripts/ui-audit.sh light styles-hub-make      Styles (S3): a real style from Hugging Face fetched,
//                                                                checked and used in a real picture (downloads it)
//   apps/desktop/scripts/ui-audit.sh light styles-advanced-make Styles (S4): Advanced, a real picture, a saved look,
//                                                                then "Make it again" choosing the style again
//   apps/desktop/scripts/ui-audit.sh light styles-recommended   Styles (S5): the Recommended styles in the Add menu and
//                                                                the dialog with the pinned file chosen (no download)
//   apps/desktop/scripts/ui-audit.sh light home-make            the home: quick starts with readiness, the "+" menu,
//                                                                typed words taken to Images by Picture, a real
//                                                                picture made, then opened from the home's Recent
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
let current = null; // the page of the step being tried, for a picture when it fails
async function attempt(name, fn) {
  try {
    await fn();
  } catch (e) {
    console.log("failed", name, e instanceof Error ? e.message.split("\n")[0] : e);
    if (current) {
      await current.screenshot({ path: join(OUT, `${name}-failed.png`) }).catch(() => {});
      const said = await current
        .locator('[data-slot="stage"]')
        .first()
        .innerText()
        .catch(() => "");
      if (said) console.log("  the stage said:", said.replace(/\s+/g, " ").slice(0, 300));
    }
  }
}

/** Wait for `ok`, but stop at once when the stage shows an error instead. */
async function untilDone(page, ok, timeout) {
  const failed = page.locator('[data-slot="stage"][data-state="error"]');
  await Promise.race([
    ok.waitFor({ timeout }),
    failed.waitFor({ timeout }).then(() => {
      throw new Error("the stage shows an error");
    }),
  ]);
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
  current = page;
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
  if (names.has("motion-editor")) {
    // The Motion graphics editor (ADR-0096 MX2): from a new project to a real video, in this window, with the
    // real engine, the real player and the real sandbox. Run it on a throwaway DESKTOP_DATA_DIR.
    await attempt("motion-editor", async () => {
      const seen = { errors: [] };
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      await open(page, "/video/builder");
      await page.getByRole("button", { name: "Video with scenes" }).click();
      const player = page.locator("hyperframes-player");
      await player.waitFor({ timeout: 30000 });
      await page.waitForFunction(
        () => document.querySelector("hyperframes-player")?.duration > 0,
        null,
        {
          timeout: 30000,
        },
      );
      seen.first = await player.evaluate((p) => ({
        duration: p.duration,
        src: p.getAttribute("src"),
      }));
      await page.getByRole("radio", { name: "9:16" }).click();
      await page.getByLabel("Project name").fill("Northbean launch");
      await page.getByLabel(/^Title/).fill("Mornings are hard.");
      await page.getByRole("button", { name: /^Quote/ }).click();
      await page.getByLabel(/^Quote/).fill("Smooth, not bitter.");
      await page.getByRole("button", { name: /^Animated title/ }).click();
      await page.getByLabel(/^Title/).fill("Try Northbean.");
      await page.getByLabel(/^Captions/).fill("Twenty percent off your first box.");
      await page.getByRole("radio", { name: "Slide" }).click();
      await page.getByRole("radio", { name: "Looks" }).click();
      await page.getByRole("button", { name: "forest" }).click();
      await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      await page.waitForFunction(
        () => document.querySelector("hyperframes-player")?.duration >= 15,
        null,
        {
          timeout: 30000,
        },
      );
      seen.afterEdits = await player.evaluate((p) => p.duration);
      await page.waitForTimeout(2500); // the player loads the saved page again
      seen.at = await player.evaluate((p) => p.currentTime);
      await shot(page, "motion-editor");
      // play across a scene boundary: the selection follows the film
      await page.getByRole("button", { name: "Scene 1, " }).click();
      await page.getByRole("button", { name: "Play" }).click();
      await page.waitForFunction(
        () => document.querySelector("hyperframes-player")?.currentTime > 5.5,
        null,
        {
          timeout: 20000,
        },
      );
      seen.selectedWhilePlaying = await page.getByText(/^Scene \d of \d$/).innerText();
      await page.getByRole("button", { name: "Pause" }).click();
      // a keyboard walk reaches the main controls; undo takes back one thing
      await page.getByRole("button", { name: /^Undo/ }).click();
      await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      await page.getByRole("button", { name: "Redo" }).click();
      await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      const AxeBuilder = require("@axe-core/playwright").default;
      const axe = await new AxeBuilder({ page })
        .include("[data-slot=scene-editor]")
        .exclude("hyperframes-player")
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();
      seen.axe = axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`);
      // the smallest window the app allows
      await page.setViewportSize({ width: 720, height: 520 });
      await page.waitForTimeout(500);
      await page.screenshot({ path: join(OUT, "motion-editor-small.png") });
      seen.smallOverflow = await page
        .locator("[data-slot=scene-editor]")
        .evaluate((el) => el.scrollWidth > el.clientWidth);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.getByRole("button", { name: "Make the video" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByText("Your video is in the Library").waitFor({ timeout: 180000 });
      await shot(page, "motion-editor-made");
      seen.check = await dialog.getByText(/Checked:/).innerText();
      seen.video = await dialog.locator("video").getAttribute("src");
      console.log(`MOTION ${JSON.stringify(seen)}`);
    });
  }
  if (scheme === "light" && names.has("styles-make")) {
    // the check of Styles stage S2 (ADR-0091): the section always in view, the Add menu with yours first,
    // Train's style chosen, a real picture made with it, and the same section on Edit, Inpaint and Reference
    await attempt("styles-make", async () => {
      await open(page, "/images/create");
      await page.getByRole("region", { name: "Styles" }).waitFor();
      await shot(page, "styles-empty");
      await page.getByRole("button", { name: /Add a style/ }).click();
      await page.waitForTimeout(400);
      await shot(page, "styles-add-menu");
      await page
        .getByRole("menuitem", { name: /\(yours\)/ })
        .first()
        .click();
      await page.waitForTimeout(600);
      await shot(page, "styles-chosen");
      await page
        .getByRole("textbox", { name: /prompt/i })
        .fill("A lighthouse on a cliff at sunrise, soft watercolour");
      await page.getByRole("button", { name: "Make the picture" }).click();
      await page.locator('[data-slot="stage"][data-state="working"]').waitFor({ timeout: 20_000 });
      await untilDone(page, page.locator('[data-slot="stage"][data-state="result"] img'), 300_000);
      await page.waitForTimeout(800);
      await shot(page, "styles-made");
      for (const [name, path] of [
        ["styles-edit", "/images/edit"],
        ["styles-inpaint", "/images/inpaint"],
        ["styles-reference", "/images/reference"],
      ]) {
        await open(page, path);
        await page.getByRole("region", { name: "Styles" }).waitFor();
        await shot(page, name);
      }
    });
  }
  if (scheme === "light" && names.has("styles-hub-make")) {
    // the check of Styles stage S3: a real style from the reviewed shortlist fetched from Hugging Face, checked,
    // chosen with its word, and a real picture made with it (WASIFYAI_AUDIT_STYLE_REPO picks another)
    await attempt("styles-hub-make", async () => {
      const repo = process.env.WASIFYAI_AUDIT_STYLE_REPO ?? "Sawata97/flux2_4b_koni_animestyle";
      await open(page, "/images/create");
      await page.getByRole("button", { name: /Add a style/ }).click();
      await page.getByRole("menuitem", { name: "From Hugging Face…" }).click();
      await page.getByLabel("Name or address").fill(repo);
      await page.getByRole("dialog").getByRole("button", { name: "Look", exact: true }).click();
      const allow = page.getByRole("button", { name: "Allow browsing Hugging Face" });
      const files = page.getByRole("radio").first();
      await Promise.race([allow.waitFor({ timeout: 30_000 }), files.waitFor({ timeout: 30_000 })]);
      if (await allow.isVisible()) await allow.click();
      await files.waitFor({ timeout: 30_000 });
      await files.check();
      await shot(page, "styles-hub-files");
      await page.getByRole("button", { name: /^Download .* and add$/ }).click();
      await page.waitForTimeout(3000);
      await shot(page, "styles-hub-getting");
      await page.getByText(/was checked and added/).waitFor({ timeout: 900_000 });
      await shot(page, "styles-hub-added");
      await page.getByRole("button", { name: "Use it in this picture" }).click();
      await page
        .getByRole("textbox", { name: /prompt/i })
        .fill("A lighthouse on a rocky cliff at sunset, a small boat in the bay");
      const word = page.getByRole("button", { name: "Use this word" }).first();
      if (await word.isVisible()) await word.click();
      await page.waitForTimeout(400);
      await shot(page, "styles-hub-chosen");
      await page.getByRole("button", { name: "Make the picture" }).click();
      await page.locator('[data-slot="stage"][data-state="working"]').waitFor({ timeout: 20_000 });
      await untilDone(page, page.locator('[data-slot="stage"][data-state="result"] img'), 300_000);
      await page.waitForTimeout(800);
      await shot(page, "styles-hub-made");
    });
  }
  if (scheme === "light" && names.has("styles-advanced-make")) {
    // the check of Styles stage S4: a style chosen with its word, Advanced (8 steps, 1280 x 720), a real picture,
    // the look saved; then a fresh screen, the picture opened and "Make it again" choosing the style again
    await attempt("styles-advanced-make", async () => {
      await open(page, "/images/create");
      await page.getByRole("button", { name: /Add a style/ }).click();
      await page.getByRole("menuitem", { name: /anime/i }).first().click();
      await page
        .getByRole("textbox", { name: /prompt/i })
        .fill("A lighthouse on a rocky cliff at sunset, a small boat in the bay");
      await page.getByRole("button", { name: "Use this word" }).first().click();
      await page.getByText("Advanced", { exact: true }).click();
      await page.getByRole("spinbutton", { name: "Steps" }).fill("8");
      await page.getByRole("spinbutton", { name: "Width" }).fill("1280");
      await page.getByRole("spinbutton", { name: "Height" }).fill("720");
      await page.waitForTimeout(300);
      await shot(page, "styles-advanced", 1400);
      await page.getByRole("button", { name: "Make the picture" }).click();
      await page.locator('[data-slot="stage"][data-state="working"]').waitFor({ timeout: 20_000 });
      await untilDone(page, page.locator('[data-slot="stage"][data-state="result"] img'), 300_000);
      await page.waitForTimeout(800);
      await shot(page, "styles-advanced-made");
      await page.getByRole("button", { name: /Saved looks/ }).click();
      await page.getByRole("menuitem", { name: "Save this look…" }).click();
      await page.getByLabel("Its name").fill("Anime wide");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await page.waitForTimeout(600);
      await page.getByRole("button", { name: /Saved looks/ }).click();
      await page.waitForTimeout(300);
      await shot(page, "styles-looks-menu");
      await page.keyboard.press("Escape");
      // a fresh screen: nothing chosen; the picture's recipe brings the style, the steps and the size back
      await open(page, "/images/create");
      await page.locator('[data-slot="recent-strip"] button[aria-label^="Open:"]').first().click();
      await page.getByRole("button", { name: "More", exact: true }).click();
      await page.getByRole("menuitem", { name: "Make it again" }).click();
      await page.locator('[data-slot="stage"][data-state="working"]').waitFor({ timeout: 20_000 });
      await page.waitForTimeout(1500);
      await shot(page, "styles-again", 1400);
      await untilDone(page, page.locator('[data-slot="stage"][data-state="result"] img'), 300_000);
      await page.waitForTimeout(800);
      await shot(page, "styles-again-made");
    });
  }
  if (scheme === "light" && names.has("styles-recommended")) {
    // Styles stage S5: the Add menu with the Recommended styles that are not here yet (nothing is fetched)
    await attempt("styles-recommended", async () => {
      await open(page, "/images/create");
      await page.getByRole("button", { name: /Add a style/ }).click();
      await page
        .getByRole("menuitem", { name: /recommended/ })
        .first()
        .waitFor();
      await shot(page, "styles-recommended");
      await page
        .getByRole("menuitem", { name: /recommended/ })
        .first()
        .click();
      await page.getByRole("radio").first().waitFor({ timeout: 30_000 });
      await page.waitForTimeout(400);
      await shot(page, "styles-recommended-dialog");
      await page.getByRole("button", { name: "Not now" }).click();
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
      await untilDone(
        page,
        page.locator('[data-slot="stage"][data-state="result"] video'),
        1_800_000,
      );
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
  if (scheme === "light" && names.has("studio-make")) {
    // the check of stage U6: a real dub with its script on the stage, and a real lip sync video
    const choose = async (list, option) => {
      await page.getByRole("combobox", { name: list }).click();
      await page.getByRole("option", { name: option }).first().click();
    };
    await attempt("dub-make", async () => {
      await open(page, "/voice/dub");
      await page.getByRole("combobox", { name: "Which recording?" }).waitFor({ timeout: 60_000 });
      await choose("Which recording?", /^Good morning/);
      // the language a voice model on this computer speaks (Kokoro: English only)
      await choose("Dub it into", process.env.WASIFYAI_AUDIT_DUB_LANGUAGE ?? "English");
      await page.getByRole("button", { name: "Write the script" }).click();
      await untilDone(page, page.getByLabel("Line 1"), 900_000);
      await page.waitForTimeout(800);
      await shot(page, "dub-script");
      await page.getByRole("button", { name: "Next: the voice" }).click();
      await page.getByRole("radio", { name: /A built-in voice/ }).click();
      await page.waitForTimeout(800);
      await shot(page, "dub-voice");
      await page.getByRole("button", { name: "Make the dub" }).click();
      await untilDone(
        page,
        page.locator('[data-slot="stage"][data-state="result"] [data-slot="player"]'),
        900_000,
      );
      await page.waitForTimeout(2500);
      await shot(page, "dub-made");
    });
    await attempt("lipsync-make", async () => {
      await open(page, "/images/create");
      await page
        .getByRole("textbox", { name: /prompt/i })
        .fill(
          "A friendly illustrated portrait of a woman looking straight at the camera, plain light background",
        );
      await page.getByRole("button", { name: "Make the picture" }).click();
      await page
        .locator('[data-slot="stage"][data-state="result"] img')
        .waitFor({ timeout: 600_000 });
      const src = await page.locator('[data-slot="stage"] img').first().getAttribute("src");
      const b64 = await page.evaluate(async (url) => {
        const bytes = new Uint8Array(await (await fetch(url)).arrayBuffer());
        let bin = "";
        for (const b of bytes) bin += String.fromCharCode(b);
        return btoa(bin);
      }, src);
      await open(page, "/voice/lip-sync");
      await page
        .getByRole("button", { name: "Choose a picture", exact: true })
        .first()
        .waitFor({ timeout: 120_000 });
      await page.locator('input[type="file"][aria-label="Choose a picture"]').setInputFiles({
        name: "portrait.png",
        mimeType: "image/png",
        buffer: Buffer.from(b64, "base64"),
      });
      await page.getByAltText("The face to bring to life").waitFor({ timeout: 60_000 });
      await page.getByRole("radio", { name: /drawing, painting/ }).click();
      await page
        .getByLabel("What should it say?")
        .fill("Hello! This video was made on this computer.");
      await page.waitForTimeout(800);
      await shot(page, "lipsync-face");
      await page.getByRole("button", { name: "Make the video" }).click();
      await page.locator('[data-slot="stage"][data-state="working"]').waitFor({ timeout: 60_000 });
      await page.waitForTimeout(15_000);
      await shot(page, "lipsync-making");
      await untilDone(
        page,
        page.locator('[data-slot="stage"][data-state="result"] video'),
        1_800_000,
      );
      await page.waitForTimeout(1500);
      await shot(page, "lipsync-made");
    });
  }
  if (scheme === "light" && names.has("music-make")) {
    // the check of stage U7: a real song made on the stage, and handed to Split into parts
    await attempt("music-make", async () => {
      await open(page, "/music/create");
      await page.getByLabel("Describe the song").waitFor({ timeout: 120_000 });
      await page.getByLabel("Describe the song").fill("warm, mellow, soft piano and brushed drums");
      await page.getByRole("button", { name: "lo-fi", exact: true }).click();
      const instrumental = page.getByRole("checkbox", { name: /No singing/ });
      if (await instrumental.count()) await instrumental.click();
      await shot(page, "music-ask");
      await page.getByRole("button", { name: /^Make the song/ }).click();
      await page.locator('[data-slot="stage"][data-state="working"]').waitFor({ timeout: 60_000 });
      await page.waitForTimeout(10_000);
      await shot(page, "music-making");
      await untilDone(
        page,
        page.locator('[data-slot="stage"][data-state="result"] [data-slot="player"]'),
        1_200_000,
      );
      await page.waitForTimeout(3000); // the waveform is read
      await shot(page, "music-made");
      await page.getByRole("button", { name: "More" }).click();
      await page.waitForTimeout(400);
      await shot(page, "music-made-more");
      await page.getByRole("menuitem", { name: /Split into parts/ }).click();
      await page.getByText("Split into parts").first().waitFor();
      await page.waitForTimeout(2500);
      await shot(page, "music-split-handed");
    });
  }
  if (scheme === "light" && names.has("library-make")) {
    // the check of stage U8: a real edit started from the Library keeps where it came from
    await attempt("library-make", async () => {
      await open(page, "/creations");
      await page.getByRole("button", { name: /^Pictures/ }).click();
      await page.waitForTimeout(800);
      await shot(page, "library");
      const card = page
        .getByRole("main")
        .getByRole("link", { name: /teapot/i })
        .first();
      await card.click();
      const detail = page.getByRole("dialog");
      await detail.getByRole("button", { name: /Edit this/ }).waitFor();
      await page.waitForTimeout(800);
      await shot(page, "library-detail");
      await detail.getByRole("button", { name: /Edit this/ }).click();
      await page.getByRole("button", { name: /Replace/ }).waitFor({ timeout: 30_000 });
      await page
        .getByRole("textbox", { name: /what should change/i })
        .fill("Make the teapot deep blue");
      await page.getByRole("button", { name: "Make the picture" }).click();
      await untilDone(page, page.locator('[data-slot="stage"][data-state="result"] img'), 600_000);
      await page.waitForTimeout(800);
      await shot(page, "library-edit-made");
      await open(page, "/creations");
      await page.getByRole("button", { name: /^Pictures/ }).click();
      await page
        .getByRole("main")
        .getByRole("link", { name: /deep blue/i })
        .first()
        .click();
      const made = page.getByRole("dialog");
      await made
        .getByRole("region", { name: "Made from" })
        .getByRole("button")
        .first()
        .waitFor({ timeout: 30_000 });
      await page.waitForTimeout(800);
      await shot(page, "library-made-from");
      await made.getByRole("region", { name: "Made from" }).getByRole("button").first().click();
      await page
        .getByRole("dialog")
        .getByRole("region", { name: "Made from this" })
        .waitFor({ timeout: 30_000 });
      await page.waitForTimeout(800);
      await shot(page, "library-made-from-this");
    });
  }
  if (names.has("a11y")) {
    // the window's screens against the same rules as the web's e2e/a11y.spec.ts (ADR-0093 U12, decision 4)
    const AxeBuilder = require("@axe-core/playwright").default;
    let failing = 0;
    for (const [name, path] of SCREENS) {
      await attempt(`a11y-${name}`, async () => {
        await open(page, path);
        const result = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
          .analyze();
        for (const v of result.violations) {
          failing += 1;
          console.log(`A11Y ${scheme} ${name}: ${v.id} (${v.impact}) ${v.help}`);
          for (const n of v.nodes.slice(0, 4))
            console.log(
              `    ${n.target.join(" ")}  ${n.failureSummary?.split("\n")[1]?.trim() ?? ""}`,
            );
        }
      });
    }
    console.log(`A11Y ${scheme}: ${SCREENS.length} screens, ${failing} rules failing`);
  }
  if (scheme === "light" && names.has("f2-parts")) {
    // stage F2: every optional part in one list, from the engine's /components
    await attempt("f2-parts", async () => {
      await open(page, "/settings");
      await page.getByRole("searchbox", { name: "Search settings" }).fill("parts");
      const list = page.getByRole("list", { name: "Optional parts" });
      await list.waitFor();
      const shown = await list.getByRole("listitem").count();
      const listed = (await engine("/components"))?.components?.length ?? -1;
      if (shown !== listed) throw new Error(`${shown} parts shown, ${listed} listed by the engine`);
      await page.waitForTimeout(500);
      await shot(page, "f2-parts", 1300);
    });
  }
  if (scheme === "light" && names.has("u11-make")) {
    await attempt("u11-settings", async () => {
      await open(page, "/settings");
      await page.getByRole("heading", { name: "What this computer can do" }).waitFor();
      await page.waitForTimeout(12_000); // each job reads its list, again once the running tools are found
      await shot(page, "u11-settings");
      await shot(page, "u11-settings-tall", 2600);
      await page.getByRole("searchbox", { name: "Search settings" }).fill("token");
      await page.waitForTimeout(400);
      await shot(page, "u11-settings-search");
      await page.getByRole("searchbox", { name: "Search settings" }).fill("");
      // saved as it changes: the switch off and on again, so the computer's setting is as it was
      const look = page.getByRole("checkbox", { name: "Look for models when the app starts" });
      const was = (await look.getAttribute("aria-checked")) === "true";
      // each change waits for the engine's answer, and the switch ends as it began (it is the person's setting)
      const saved = () =>
        page.waitForResponse(
          (r) => r.url().includes("/desktop/discovery/settings") && r.request().method() === "PUT",
          { timeout: 15_000 },
        );
      await Promise.all([saved(), look.click()]);
      await Promise.all([saved(), look.click()]);
      if (((await look.getAttribute("aria-checked")) === "true") !== was)
        throw new Error("Look for models did not end as it began");
      const after = await engine("/desktop/discovery");
      if (after && after.enabled !== was) throw new Error("the engine kept the switch changed");
      await page.getByRole("radio", { name: "Dark" }).click();
      await page.waitForTimeout(600);
      await shot(page, "u11-settings-dark");
      await page.getByRole("radio", { name: "Like the computer" }).click();
    });
    await attempt("u11-models", async () => {
      await open(page, "/models");
      await page.getByRole("table").waitFor();
      await page.waitForTimeout(1000);
      await shot(page, "u11-models");
      await open(page, "/images/create");
      await page.locator('button[aria-haspopup="dialog"]').first().click();
      await page.waitForTimeout(1200);
      await shot(page, "u11-picker");
      await page.keyboard.press("Escape");
    });
  }
  if (scheme === "light" && names.has("u10-make")) {
    // the check of stage U10: the four screens with real work in them
    await attempt("u10-train", async () => {
      await open(page, "/train");
      await page.getByRole("region", { name: "What to teach" }).waitFor();
      await page.waitForTimeout(1500);
      await shot(page, "u10-train", 1300);
    });
    await attempt("u10-notebook", async () => {
      if (!NOTEBOOK) throw new Error("no notebook to open");
      await open(page, `/notebooks/${NOTEBOOK}`);
      await page.getByRole("button", { name: "Report", exact: true }).click();
      await page
        .getByRole("form", { name: "Make a report" })
        .getByRole("button", { name: "Create" })
        .click();
      // a real report by the chat model, shown as a card in Outputs
      await page
        .locator('[data-slot="output-card"]')
        .filter({ hasText: /Report · / })
        .first()
        .waitFor({ timeout: 600_000 });
      await page.waitForTimeout(800);
      await shot(page, "u10-notebook-output");
      await page
        .locator('[data-slot="output-card"]')
        .first()
        .getByRole("button", { name: /^Rename/ })
        .click();
      await page.waitForTimeout(400);
      await shot(page, "u10-notebook-rename");
      await page.keyboard.press("Escape");
    });
    await attempt("u10-motion", async () => {
      await open(page, "/video/builder");
      await shot(page, "u10-motion-start");
      await page.getByRole("button", { name: "Or fill in the form yourself" }).click();
      await page.getByLabel("Title").fill("Launch day");
      await page.getByRole("button", { name: "Make the video" }).click();
      await untilDone(
        page,
        page.locator('[data-slot="stage"][data-state="result"] video'),
        600_000,
      );
      await page.waitForTimeout(1500);
      await shot(page, "u10-motion-made");
    });
    await attempt("u10-3d", async () => {
      await open(page, "/images/3d");
      await shot(page, "u10-3d-start");
      // the newest picture of the Library, as a file, checked for real (its cut-out); no model is made
      const images = (await engine("/products/wasifyai-image/images?limit=10"))?.images ?? [];
      const teapot = images.find((i) => /teapot/i.test(i.prompt)) ?? images[0];
      if (!teapot) throw new Error("no picture to start from");
      const res = await fetch(
        teapot.image_url.startsWith("http") ? teapot.image_url : `${BASE}${teapot.image_url}`,
        {
          headers: { authorization: `Bearer ${TOKEN}` },
        },
      );
      const buffer = Buffer.from(await res.arrayBuffer());
      await page
        .getByLabel("Choose a picture")
        .setInputFiles({ name: "teapot.png", mimeType: "image/png", buffer });
      await page.getByRole("img", { name: "The object cut out" }).waitFor({ timeout: 600_000 });
      await page.waitForTimeout(1000);
      await shot(page, "u10-3d-check");
    });
  }
  if (scheme === "light" && names.has("home-make")) {
    // the check of stage U9: the home's quick starts carry the words typed, and Recent opens in the Library
    await attempt("home-make", async () => {
      await open(page, "/");
      await page.getByRole("navigation", { name: "Quick starts" }).waitFor();
      await page.waitForTimeout(1500); // each start reads whether its model is ready
      await shot(page, "home-start");
      await page.getByRole("button", { name: /^More options/ }).click();
      await page.waitForTimeout(400);
      await shot(page, "home-plus");
      await page.keyboard.press("Escape");
      const words = "A lighthouse on a cliff in thick fog, one beam of light";
      await page.getByRole("textbox", { name: "Message" }).fill(words);
      await page
        .getByRole("navigation", { name: "Quick starts" })
        .getByRole("button", { name: /^Picture/ })
        .click();
      const prompt = page.getByRole("textbox", { name: /prompt/i });
      await prompt.waitFor({ timeout: 30_000 });
      if ((await prompt.inputValue()) !== words)
        throw new Error("the words typed did not reach Images");
      await shot(page, "home-to-images");
      await page.getByRole("button", { name: "Make the picture" }).click();
      await untilDone(page, page.locator('[data-slot="stage"][data-state="result"] img'), 600_000);
      await open(page, "/");
      const recent = page
        .getByRole("region", { name: "Recent" })
        .getByRole("button", { name: /lighthouse/i })
        .first();
      await recent.waitFor({ timeout: 30_000 });
      await page.waitForTimeout(800);
      await shot(page, "home-recent");
      await recent.click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: /Edit this/ })
        .waitFor({ timeout: 30_000 });
      await page.waitForTimeout(800);
      await shot(page, "home-recent-opened");
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
        // Train reopens the set the last step started: go back to the front door first
        const back = page.getByRole("button", { name: "Back to Train models" });
        if (await back.count()) {
          await back.first().click();
          await page.getByRole("region", { name: "What to teach" }).waitFor();
        }
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
