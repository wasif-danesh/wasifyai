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
//   apps/desktop/scripts/ui-audit.sh light coding-setup         The coding engine (ADR-0102, C1a) set up from Settings,
//                                                               Optional parts, with the real downloads; then
//                                                               coding-repair and coding-remove the same way
//   WASIFYAI_AUDIT_FOLDER=<a project> apps/desktop/scripts/ui-audit.sh light code-plan
//                                                               Code (ADR-0101, C1b): the first screen, a folder
//                                                               chosen, a question asked of a real model in Plan
//                                                               and its answer; needs the coding engine set up and
//                                                               a model that is ready (CODING_OLLAMA_URL for the
//                                                               local one); use a throwaway DESKTOP_DATA_DIR
//   WASIFYAI_AUDIT_FOLDER=<a project> apps/desktop/scripts/ui-audit.sh light code-edit
//                                                               Code (C2): a session in "Ask me" on a real model: a
//                                                               change, the card for a file Undo cannot put back
//                                                               (yes, no, Allow for this project, Stop), the Changes
//                                                               tab, Undo and Bring it back checked on disk. The
//                                                               project needs src/pages/home.html, a .env with
//                                                               OPEN=0 and a .gitignore naming it; a throwaway
//                                                               DESKTOP_DATA_DIR as for code-plan
//   WASIFYAI_AUDIT_FOLDER=<an empty folder> apps/desktop/scripts/ui-audit.sh light code-check
//                                                               Code (C3): the check set and tried, a question in a
//                                                               project whose check fails, a failed round that goes
//                                                               back and a pass, a two-minute check with the screen
//                                                               live, Stop during a check, "needs you" after three
//                                                               rounds, the person's terminal, a delete that is
//                                                               asked first and undone, and git init by the agent;
//                                                               all read back from disk. A throwaway folder and
//                                                               DESKTOP_DATA_DIR as for code-plan
//   WASIFYAI_AUDIT_FOLDER=<an empty folder> apps/desktop/scripts/ui-audit.sh light code-build
//                                                               Code (C4): a new project from the starter, its
//                                                               preview and check, then "a to-do web app with a
//                                                               logo" built by a real model with the logo made by
//                                                               Wasify AI's picture product; read back from disk
//                                                               and used in the running page. Needs the coding
//                                                               engine, Node for coding projects and a picture
//                                                               model in DESKTOP_DATA_DIR
//   WASIFYAI_AUDIT_FOLDER=<an empty folder> apps/desktop/scripts/ui-audit.sh light code-extensions
//                                                               Extensions (X2): the short list for a project, a
//                                                               public skill's text, one of ours firing in a real
//                                                               session, ours switched off and a public one on, a
//                                                               skill added from a folder whose rule the answer
//                                                               follows, and its removal. A throwaway
//                                                               DESKTOP_DATA_DIR with the coding engine
//   WASIFYAI_AUDIT_FOLDER=<an empty folder> apps/desktop/scripts/ui-audit.sh light code-scheduled
//                                                               Scheduled (C6) and a plugin (X3): a schedule from a
//                                                               template, Run now on a copy with the project read
//                                                               back untouched, the changes applied; a plugin with
//                                                               a hook that stays off until approved, then runs. A
//                                                               throwaway DESKTOP_DATA_DIR with the coding engine
//   apps/desktop/scripts/ui-audit.sh light u11-make             Settings (what this computer can do, the groups, a
//                                                                search, the theme, a setting saved as it changes),
//                                                                the Models page and the picker with their dots
//   apps/desktop/scripts/ui-audit.sh light u10-make             Teach's front door, a real notebook report as a card,
//                                                                a real Motion graphics video on the frame, and a real
//                                                                3D picture check (its cut-out) on the stage
//   apps/desktop/scripts/ui-audit.sh light motion-assistant     The editor's assistant (ADR-0096 MX3) on the real language
//                                                                model: a brief, edits in words, Undo, a video; on this
//                                                                computer's data, and it deletes what it made
//   apps/desktop/scripts/ui-audit.sh light creative             Creative Studio (ADR-0090 CS1): a brief, a real plan on the
//                                                                chosen chat model, edits, Undo, axe, a phone width; needs a
//                                                                song in Your music and a throwaway DESKTOP_DATA_DIR
//   apps/desktop/scripts/ui-audit.sh light creative-shots       The Shots step (ADR-0090 CS2): a real redo, takes, the Image, Video and
//                                                                Add tabs, a real file added, axe, a phone. Needs a project "cs2 real" with
//                                                                its stills in a throwaway DESKTOP_DATA_DIR, and CS2_FILES with mine.png
//   apps/desktop/scripts/ui-audit.sh light creative-motion      Motion (ADR-0090 CS4): the Motion panel and its start, a real draft
//                                                                clip of one shot, the clip's badge, axe, the smallest window. Needs a project
//                                                                "cs4 real" with its stills in a throwaway DESKTOP_DATA_DIR
//   apps/desktop/scripts/ui-audit.sh light creative-cut         The Cut step (ADR-0090 CS3): the timeline's buttons and keys, a title, the
//                                                                Voice tab, Make the video for real, Save a copy, axe, the smallest window.
//                                                                Needs a project "cs3 real" with its stills in a throwaway DESKTOP_DATA_DIR
//   apps/desktop/scripts/ui-audit.sh light motion-pack          The marketing pack (ADR-0096 MX7): a starting point, a
//                                                                brand with a real logo, every shape made for real;
//                                                                needs MOTION_FIXTURES and a throwaway DESKTOP_DATA_DIR
//   apps/desktop/scripts/ui-audit.sh light motion-make          The Make panel (ADR-0096 MX6): real models, a real
//                                                                voiceover with timed captions and a real video; a
//                                                                throwaway DESKTOP_DATA_DIR with models and components linked
//   apps/desktop/scripts/ui-audit.sh light motion-media         Media and sound (ADR-0096 MX5): real files through the
//                                                                screen and a real video; needs MOTION_FIXTURES and a
//                                                                throwaway DESKTOP_DATA_DIR
//   apps/desktop/scripts/ui-audit.sh light motion-arrange       Arranging (ADR-0096 MX4): drag and resize on the real
//                                                                preview, and a real video; prints where each says it
//                                                                is; use a throwaway DESKTOP_DATA_DIR
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
window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener() {} };
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
      case "stay_open_get": return { supported: true, on: window.__wasifyStays === true };
      case "stay_open_set": window.__wasifyStays = !window.__wasifyStays; return { supported: true, on: window.__wasifyStays };
      case "plugin:dialog|open": return window.__wasifyAuditFolder ?? ${JSON.stringify(process.env.WASIFYAI_AUDIT_FOLDER ?? null)};
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
  if (names.has("motion-media")) {
    // Media and sound (ADR-0096 MX5): a real picture, clip and sound added through the screen, then a real
    // video. MOTION_FIXTURES names a folder with can.png, clip-h264.mp4, music.wav and voice.wav. Run it on
    // a throwaway DESKTOP_DATA_DIR.
    await attempt("motion-media", async () => {
      const seen = { errors: [] };
      const fixtures = process.env.MOTION_FIXTURES;
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      const saved = async () => {
        await page.waitForTimeout(700);
        await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      };
      await open(page, "/video/builder");
      await page.getByRole("button", { name: "Start empty" }).click();
      const player = page.locator("hyperframes-player");
      await page.waitForFunction(
        () => document.querySelector("hyperframes-player")?.duration > 0,
        null,
        {
          timeout: 30000,
        },
      );
      await page.getByRole("radio", { name: "16:9" }).click();
      await page.getByRole("radio", { name: "Media", exact: true }).click();
      const add = page.getByLabel("Add a photo or clip");
      await add.setInputFiles(join(fixtures, "can.png"));
      await page.getByRole("button", { name: "can.png" }).waitFor({ timeout: 30000 });
      await add.setInputFiles(join(fixtures, "clip-h264.mp4"));
      await page.getByRole("button", { name: "clip-h264.mp4" }).waitFor({ timeout: 60000 });
      await page.getByRole("button", { name: "can.png" }).click();
      await page.getByRole("button", { name: "Place on scene" }).click();
      await saved();
      // a second scene, with the clip behind it, trimmed, with its own sound
      await page.getByRole("radio", { name: "Add", exact: true }).click();
      await page.getByRole("button", { name: /^Animated title/ }).click();
      await saved();
      await page.getByRole("radio", { name: "Media", exact: true }).click();
      await page.getByRole("button", { name: "clip-h264.mp4" }).click();
      await page.getByRole("button", { name: "Use as background" }).click();
      await page.getByRole("radio", { name: /^Scene 2/ }).click();
      await page.getByLabel(/Starts .* seconds in/).fill("3");
      await page.getByLabel("Its own sound").fill("0.5");
      await saved();
      // a sound on the scene, music for the whole video
      await page.getByRole("radio", { name: "Sound", exact: true }).click();
      await page.getByLabel("Add a sound").setInputFiles(join(fixtures, "voice.wav"));
      await page.getByLabel("Repeat it to fill the scene").waitFor({ timeout: 30000 });
      await saved();
      await page.getByLabel("Add a music file").setInputFiles(join(fixtures, "music.wav"));
      await page.getByLabel("Repeat", { exact: true }).waitFor({ timeout: 60000 });
      await saved();
      await page.waitForTimeout(4000);
      await shot(page, "motion-media");
      const frame = () => page.frames().find((f) => f.url().includes("/live/"));
      seen.page = await frame().evaluate(() => ({
        film: window.__timelines?.main?.time(),
        videos: [...document.querySelectorAll("video")].map((v) => ({
          ready: v.readyState,
          error: v.error?.message ?? null,
          at: v.currentTime,
        })),
        audios: document.querySelectorAll("audio").length,
        images: [...document.querySelectorAll("img")].map((i) => i.naturalWidth),
      }));
      // playing: the clip moves in the preview
      page.on("console", (m) => {
        if (["error", "warning"].includes(m.type())) seen.errors.push(m.text().slice(0, 200));
      });
      await player.evaluate((p) => {
        window.__seen = [];
        for (const name of ["play", "pause", "ended", "error", "waiting", "ready"]) {
          p.addEventListener(name, () => window.__seen.push([name, p.currentTime]));
        }
      });
      const before = await player.evaluate((p) => p.currentTime);
      await page.getByRole("button", { name: "Play" }).click();
      await page.waitForTimeout(2500);
      seen.playing = {
        before,
        after: await player.evaluate((p) => [p.currentTime, p.paused, window.__seen]),
        button: await page
          .locator('[aria-label="Play"],[aria-label="Pause"]')
          .getAttribute("aria-label"),
        videos: await frame().evaluate(() =>
          [...document.querySelectorAll("video")].map((v) => [
            v.currentTime,
            v.paused,
            v.readyState,
            v.networkState,
          ]),
        ),
        audios: await frame().evaluate(() =>
          [...document.querySelectorAll("audio")].map((v) => [
            v.currentTime,
            v.paused,
            v.readyState,
            v.networkState,
            v.error?.message ?? null,
          ]),
        ),
      };
      console.log(`MEDIAPLAY ${JSON.stringify(seen)}`);
      if (await page.getByRole("button", { name: "Pause" }).count()) {
        await page.getByRole("button", { name: "Pause" }).click();
      }
      const AxeBuilder = require("@axe-core/playwright").default;
      const axe = await new AxeBuilder({ page })
        .include("[data-slot=scene-editor]")
        .exclude("hyperframes-player")
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();
      seen.axe = axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`);
      await page.getByRole("button", { name: "Make the video" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("button", { name: "Make the video" }).click();
      await dialog.getByText("Your video is in the Library").waitFor({ timeout: 240000 });
      await shot(page, "motion-media-made");
      seen.check = await dialog.getByText(/Checked:/).innerText();
      console.log(`MEDIA ${JSON.stringify(seen)}`);
    });
  }
  // the Shots step, on a project that already has its stills (ADR-0090 CS2): a real redo, a take chosen, the tabs
  if (names.has("creative-shots")) {
    await attempt("creative-shots", async () => {
      const seen = { errors: [], console: [] };
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      page.on("console", (m) => m.type() === "error" && seen.console.push(m.text().slice(0, 200)));
      const axe = async () => {
        const AxeBuilder = require("@axe-core/playwright").default;
        const found = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
          .analyze();
        return found.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`);
      };
      await open(page, "/creative");
      await page.getByRole("button", { name: /^cs2 real/ }).click();
      await page.getByRole("radio", { name: "Shots" }).waitFor({ timeout: 15000 });
      await page.waitForTimeout(1500);
      await shot(page, "creative-plan-stills", 900);
      await page.getByRole("radio", { name: "Shots" }).click();
      await page.getByRole("button", { name: "Shot 1", exact: false }).first().click();
      await page.waitForTimeout(2500);
      await shot(page, "creative-shots", 900);
      seen.axeShots = await axe();
      seen.preview = await page
        .locator("video")
        .first()
        .evaluate(async (v) => {
          await new Promise((r) =>
            v.readyState > 0 ? r() : v.addEventListener("loadedmetadata", r),
          );
          return { seconds: v.duration, width: v.videoWidth, height: v.videoHeight };
        });
      const stage = page.getByRole("region", { name: "The shots" });
      const started = Date.now();
      await stage.getByRole("button", { name: "Make it again" }).click();
      await page.getByRole("button", { name: "Version 2 of shot 1" }).waitFor({ timeout: 300000 });
      seen.redo_s = Math.round((Date.now() - started) / 1000);
      await page.waitForTimeout(800);
      await shot(page, "creative-take", 900);
      seen.chosenAfterRedo = await page
        .getByRole("button", { name: "Version 2 of shot 1" })
        .getAttribute("aria-pressed");
      await page.getByRole("button", { name: "Version 1 of shot 1" }).click();
      await page.waitForTimeout(800);
      seen.chosenBack = await page
        .getByRole("button", { name: "Version 1 of shot 1" })
        .getAttribute("aria-pressed");
      seen.previewStale = await page.getByText(/The shots have changed since/).count();
      const make = page.getByRole("tablist", { name: "Make something for this project" });
      await make.getByRole("tab", { name: "Image" }).click();
      await page.waitForTimeout(800);
      seen.imageTabSays = await page.getByText(/What you make here is a version of shot 1/).count();
      seen.imageButton = await page.getByRole("button", { name: /Make the picture/ }).count();
      await shot(page, "creative-tab-image", 900);
      seen.axeImage = await axe();
      await make.getByRole("tab", { name: "Video" }).click();
      await page.waitForTimeout(800);
      seen.videoButton = await page.getByRole("button", { name: /Make the (video|clip)/ }).count();
      await shot(page, "creative-tab-video", 900);
      seen.axeVideo = await axe();
      await make.getByRole("tab", { name: "Add" }).click();
      await page.waitForTimeout(800);
      await page
        .getByLabel("Choose a picture, clip or sound to add")
        .setInputFiles(join(process.env.CS2_FILES ?? ".", "mine.png"));
      await page.getByRole("button", { name: "Version 3 of shot 1" }).waitFor({ timeout: 30000 });
      seen.dropped = await page
        .getByRole("button", { name: "Version 3 of shot 1" })
        .getAttribute("aria-pressed");
      await shot(page, "creative-tab-add", 900);
      seen.axeAdd = await axe();
      console.log(`CREATIVESHOTS ${JSON.stringify(seen)}`);
    });
  }

  if (names.has("creative-motion")) {
    await attempt("creative-motion", async () => {
      const seen = { errors: [], console: [] };
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      page.on("console", (m) => m.type() === "error" && seen.console.push(m.text().slice(0, 200)));
      const axe = async () => {
        const AxeBuilder = require("@axe-core/playwright").default;
        const found = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
          .analyze();
        return found.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`);
      };
      await open(page, "/creative");
      await page.getByRole("button", { name: /^cs4 real/ }).click();
      await page.getByRole("radio", { name: "Shots" }).waitFor({ timeout: 15000 });
      await page.getByRole("radio", { name: "Shots" }).click();
      const motion = page.getByRole("region", { name: "Motion" });
      await motion.getByText(/clips? to make|They have their clips/).waitFor({ timeout: 30000 });
      // Make it better is the default since 2026-11-05; the draft is picked
      await motion.getByRole("radio", { name: "Draft 30 seconds" }).click();
      await page.waitForTimeout(1500);
      seen.draftSays = await motion.locator("p").first().innerText();
      await shot(page, "creative-motion", 900);
      seen.axeMotion = await axe();
      await motion.getByRole("combobox", { name: "Where the 30 seconds start" }).click();
      const options = page.getByRole("option");
      seen.starts = await options.allInnerTexts();
      await options.last().click();
      await page.waitForTimeout(1500);
      seen.laterSays = await motion.locator("p").first().innerText();
      await motion.getByRole("radio", { name: "Make it better" }).click();
      await page.waitForTimeout(1500);
      seen.betterSays = await motion.locator("p").first().innerText();
      await shot(page, "creative-motion-better", 900);
      await motion.getByRole("radio", { name: "Draft 30 seconds" }).click();
      // a real draft clip of the last shot, which the excerpt did not reach
      const last = page
        .getByRole("list")
        .filter({ has: page.getByRole("button", { name: /^Shot 1\b/ }) })
        .getByRole("button")
        .last();
      seen.lastShot = await last.getAttribute("aria-label");
      await last.click();
      const started = Date.now();
      await page.getByRole("button", { name: "Make a draft clip" }).click();
      await page
        .getByText("Making the clips")
        .or(page.getByText(/^Animating shot/))
        .first()
        .waitFor({ timeout: 30000 });
      await shot(page, "creative-motion-making", 900);
      seen.axeMaking = await axe();
      // the Motion panel comes back when the run has ended
      await motion.waitFor({ state: "visible", timeout: 600000 });
      seen.run = await page.getByRole("status").allInnerTexts();
      seen.clip_s = Math.round((Date.now() - started) / 1000);
      await page.waitForTimeout(1000);
      seen.lastShotAfter = await last.getAttribute("aria-label");
      await shot(page, "creative-motion-clip", 900);
      seen.axeClip = await axe();
      const make = page.getByRole("tablist", { name: "Make something for this project" });
      await make.getByRole("tab", { name: "Video" }).click();
      await page.waitForTimeout(800);
      seen.settingChips = await page.getByRole("button", { name: /^(Final|Draft)/ }).count();
      await shot(page, "creative-motion-video-tab", 900);
      seen.axeVideoTab = await axe();
      // the desktop window's smallest size
      await page.setViewportSize({ width: 720, height: 700 });
      await page.waitForTimeout(800);
      seen.narrow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      seen.motionAtPhone = await motion.count();
      await page.screenshot({ path: join(OUT, "creative-motion-phone.png") });
      await page.setViewportSize({ width: 1440, height: 900 });
      console.log(`CREATIVEMOTION ${JSON.stringify(seen)}`);
    });
  }

  if (names.has("creative-cut")) {
    await attempt("creative-cut", async () => {
      const seen = { errors: [], console: [] };
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      page.on("console", (m) => m.type() === "error" && seen.console.push(m.text().slice(0, 200)));
      const axe = async () => {
        const AxeBuilder = require("@axe-core/playwright").default;
        const found = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
          .analyze();
        return found.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`);
      };
      await open(page, "/creative");
      await page.getByRole("button", { name: /^cs3 real/ }).click();
      await page.getByRole("radio", { name: "Cut" }).click();
      const pictures = page.getByRole("list", { name: "Pictures" });
      await pictures.waitFor({ timeout: 15000 });
      await page.waitForTimeout(1500);
      await shot(page, "creative-cut", 900);
      seen.axeCut = await axe();
      seen.pieces = await pictures.getByRole("button").count();
      seen.captions = await page
        .getByRole("list", { name: "Captions" })
        .getByRole("button")
        .count();
      const second = pictures.getByRole("button").nth(1);
      seen.before = await second.getAttribute("aria-label");
      await second.click();
      await page.getByRole("button", { name: "Longer" }).click();
      await page.waitForTimeout(800);
      seen.longer = await pictures.getByRole("button").nth(1).getAttribute("aria-label");
      await page.getByRole("button", { name: "Fade in" }).click();
      await page.waitForTimeout(800);
      seen.faded = await pictures.getByRole("button").nth(1).getAttribute("aria-label");
      await pictures.getByRole("button").nth(1).focus();
      await page.keyboard.press("z");
      await page.waitForTimeout(800);
      seen.afterZ = await pictures.getByRole("button").nth(1).getAttribute("aria-label");
      await page.keyboard.press("Shift+Z");
      await page.waitForTimeout(800);
      seen.afterShiftZ = await pictures.getByRole("button").nth(1).getAttribute("aria-label");
      await page.keyboard.press("s");
      await page.waitForTimeout(800);
      seen.afterS = await pictures.getByRole("button").count();
      await page.keyboard.press("z");
      await page.waitForTimeout(800);
      const make = page.getByRole("tablist", { name: "Make something for this project" });
      await make.getByRole("tab", { name: "Titles" }).click();
      await page.getByLabel("Words").fill("Dawn drive");
      await page.getByRole("button", { name: "Add", exact: true }).click();
      await page.waitForTimeout(800);
      seen.title = await page.getByRole("button", { name: /^Title at 0:00: Dawn drive/ }).count();
      await shot(page, "creative-cut-titles", 900);
      seen.axeTitles = await axe();
      await make.getByRole("tab", { name: "Voice" }).click();
      await page.waitForTimeout(800);
      seen.voiceLines = await page.getByRole("textbox", { name: /^Words at/ }).count();
      await shot(page, "creative-cut-voice", 900);
      seen.axeVoice = await axe();
      const caption = page.getByRole("list", { name: "Captions" }).getByRole("button").nth(1);
      await caption.click();
      await page.getByRole("button", { name: "A beat later" }).click();
      await page.waitForTimeout(800);
      seen.captionMoved = await page
        .getByRole("list", { name: "Captions" })
        .getByRole("button")
        .nth(1)
        .getAttribute("aria-label");
      const kept = page.getByRole("list", { name: "Kept in Your videos" }).getByRole("listitem");
      const before = await kept.count();
      const started = Date.now();
      await page.getByRole("button", { name: "Make the video" }).click();
      await kept.nth(before).waitFor({ timeout: 1200000 }); // one more than there were: this one
      seen.make_s = Math.round((Date.now() - started) / 1000);
      await page.waitForTimeout(1500);
      seen.video = await page.getByLabel("The video of the cut").evaluate(async (v) => {
        await new Promise((r) =>
          v.readyState > 0 ? r() : v.addEventListener("loadedmetadata", r),
        );
        return { seconds: v.duration, width: v.videoWidth, height: v.videoHeight };
      });
      await page.getByLabel("The video of the cut").evaluate((v) => {
        v.currentTime = 1;
      });
      await page.waitForTimeout(1500);
      await shot(page, "creative-cut-made", 900);
      seen.axeMade = await axe();
      await page.getByRole("button", { name: "Save a copy" }).click();
      await page.getByText(/^Saved to /).waitFor({ timeout: 60000 });
      seen.saved = await page.getByText(/^Saved to /).textContent();
      await page.setViewportSize({ width: 720, height: 700 });
      await page.waitForTimeout(1000);
      seen.narrow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      await page.getByRole("region", { name: "Timeline" }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: join(OUT, "creative-cut-phone.png") });
      await page.setViewportSize({ width: 1440, height: 900 });
      console.log(`CREATIVECUT ${JSON.stringify(seen)}`);
    });
  }

  if (names.has("creative-shots") || names.has("creative-shots-phone")) {
    await attempt("creative-shots-phone", async () => {
      const seen = {};
      // the smallest the desktop window goes (tauri.conf.json)
      await page.setViewportSize({ width: 720, height: 700 });
      await open(page, "/creative");
      await page.getByRole("button", { name: /^cs2 real/ }).click();
      await page.getByRole("radio", { name: "Shots" }).click();
      await page.waitForTimeout(2000);
      const wide = () =>
        page.evaluate(() => {
          const over = document.documentElement.scrollWidth - window.innerWidth;
          const who = [...document.querySelectorAll("body *")]
            .filter(
              (e) => e.getBoundingClientRect().right > window.innerWidth + 1 && e.checkVisibility(),
            )
            .slice(0, 6)
            .map((e) => `${e.tagName}.${String(e.className).slice(0, 60)}`);
          return { over, who };
        });
      await page.screenshot({ path: join(OUT, "creative-shots-phone.png") });
      const make = page.getByRole("tablist", { name: "Make something for this project" });
      for (const tab of ["Image", "Video", "Add"]) {
        await make.getByRole("tab", { name: tab }).click();
        await page.waitForTimeout(500);
        seen[tab] = await wide();
      }
      await make.getByRole("tab", { name: "Image" }).click();
      await make.scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      await page.screenshot({ path: join(OUT, "creative-tab-image-phone.png") });
      await page.setViewportSize({ width: 1440, height: 900 });
      console.log(`CREATIVEPHONE ${JSON.stringify(seen)}`);
    });
  }

  if (names.has("creative")) {
    await attempt("creative", async () => {
      const seen = { errors: [] };
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      const axe = async () => {
        const AxeBuilder = require("@axe-core/playwright").default;
        const found = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
          .analyze();
        return found.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`);
      };
      await open(page, "/creative");
      await page.getByRole("heading", { name: "Creative Studio" }).waitFor({ timeout: 15000 });
      await page.waitForTimeout(600);
      await shot(page, "creative-list");
      seen.axeList = await axe();
      await page.getByRole("button", { name: "New project" }).first().click();
      await page.getByRole("combobox", { name: "Song" }).click();
      await page.getByRole("option").first().click();
      await page
        .getByLabel("What is the video about?")
        .fill("A woman leaves the city in a borrowed grey car and drives the long way home");
      await page.getByRole("button", { name: "Add a person" }).click();
      await page.getByLabel("Name of person 1").fill("Mira");
      await page.getByLabel("How Mira looks").fill("a woman in her thirties, green jacket");
      await page
        .getByLabel(/^Places/)
        .fill("a city street at dawn\na petrol station\na coast road");
      await shot(page, "creative-brief", 1300);
      seen.axeBrief = await axe();
      const started = Date.now();
      await page.getByRole("button", { name: "Plan it" }).click();
      await page.getByRole("region", { name: "Progress" }).waitFor({ timeout: 15000 });
      await shot(page, "creative-planning");
      await page.getByRole("textbox", { name: "What shot 1 shows" }).waitFor({ timeout: 300000 });
      seen.planned_s = Math.round((Date.now() - started) / 1000);
      await page.waitForTimeout(400);
      await shot(page, "creative-plan", 900);
      seen.axePlan = await axe();
      const plan = page.getByRole("region", { name: "The plan" });
      const saved = (n) => page.getByText(`Plan ${n} · saved`).waitFor({ timeout: 120000 });
      const box = page.getByRole("textbox", { name: "What shot 2 shows" });
      await box.fill("Mira turns the key in the grey car at the kerb.");
      await box.blur();
      await page.waitForTimeout(500);
      seen.edited = await page.getByRole("textbox", { name: "What shot 2 shows" }).inputValue();
      await page.getByRole("button", { name: "End shot 1 one beat later" }).click();
      await page.waitForTimeout(500);
      await plan.getByRole("button", { name: "Undo" }).click();
      await page.waitForTimeout(500);
      await plan.getByRole("button", { name: "Undo" }).click();
      await page.waitForTimeout(500);
      seen.undone = await page.getByRole("textbox", { name: "What shot 2 shows" }).inputValue();
      await page.getByRole("button", { name: "Planning log" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Close" }).waitFor();
      await page.waitForTimeout(500);
      await shot(page, "creative-log");
      await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
      // the tabs: arrow keys, the ones to come, then Add from the Library
      const make = page.getByRole("tablist", { name: "Make something for this project" });
      seen.tabs = await make.getByRole("tab").allTextContents();
      await make.getByRole("tab", { name: "Ask" }).focus();
      await page.keyboard.press("ArrowLeft");
      await page.waitForTimeout(200);
      seen.arrowTo = await make.locator('[aria-selected="true"]').textContent();
      await make.getByRole("tab", { name: "Titles" }).click();
      seen.titlesSay = await page.getByText(/come with the Cut step/).textContent();
      await page.getByRole("button", { name: "Shot 3", exact: true }).click();
      await make.getByRole("tab", { name: "Add" }).click();
      const first = page.getByRole("button", { name: /^Add: / }).first();
      await first.waitFor({ timeout: 15000 });
      seen.added = await first.getAttribute("aria-label");
      await first.click();
      const rail = page.getByRole("complementary", { name: "Media of this project" });
      await rail.getByRole("button", { name: /^Take out of this project/ }).waitFor();
      seen.rail = await rail.getByRole("listitem").allInnerTexts();
      await page.waitForTimeout(800);
      await shot(page, "creative-add", 900);
      seen.axeAdd = await axe();
      // Ask, with the real model: a change on the selected shot, shown at once, and its card's Undo
      await make.getByRole("tab", { name: "Ask" }).click();
      // a shot the plan has on Hold: the plan sets some to Animate by itself
      const motions = page.getByRole("combobox", { name: /^Motion of shot \d+$/ });
      const count = await motions.count();
      let held = 0;
      for (let i = 0; i < count && !held; i++) {
        if ((await motions.nth(i).textContent()) === "Hold") held = i + 1;
      }
      const motion = page.getByRole("combobox", { name: `Motion of shot ${held}`, exact: true });
      seen.askShot = held;
      await page.getByRole("button", { name: `Shot ${held}`, exact: true }).click();
      await page.getByPlaceholder("Ask anything").last().fill("Make this shot animate.");
      await page.keyboard.press("Enter");
      await saved(2);
      seen.askMotion = await motion.textContent();
      await page.waitForTimeout(3000);
      await shot(page, "creative-ask", 900);
      seen.axeAsk = await axe();
      const panel = page.getByRole("complementary", { name: "Make panel" });
      seen.askCards = await panel.getByRole("button", { name: /^undo/i }).allTextContents();
      await panel.getByRole("button", { name: "Undo", exact: true }).first().click();
      await saved(1);
      seen.askUndone = await motion.textContent();
      await page.getByPlaceholder("Ask anything").last().fill("What does this shot show?");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(15000);
      seen.askedChanged = (await page.getByText("Plan 1 · saved").count()) === 0;
      await shot(page, "creative-ask-question", 900);
      // the rest of the width steps: stacked, the tabs as a dock
      await page.setViewportSize({ width: 1000, height: 800 });
      await page.waitForTimeout(400);
      await shot(page, "creative-1000");
      await page.getByRole("button", { name: "Hide the side menu" }).click();
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(400);
      seen.phoneOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth,
      );
      seen.axePhone = await axe();
      await page.screenshot({ path: join(OUT, "creative-plan-phone.png") });
      await page
        .getByRole("tablist", { name: "Make something for this project" })
        .scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      await page.screenshot({ path: join(OUT, "creative-make-phone.png") });
      await page.setViewportSize({ width: 1440, height: 900 });
      console.log(JSON.stringify(seen, null, 1));
    });
  }

  if (names.has("motion-pack")) {
    // The marketing pack (ADR-0096 MX7): a starting point, a brand set up with a real logo, and one
    // project made in every shape. MOTION_FIXTURES has can.png. Run it on a throwaway DESKTOP_DATA_DIR.
    await attempt("motion-pack", async () => {
      const seen = { errors: [] };
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      const saved = async () => {
        await page.waitForTimeout(700);
        await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      };
      const ready = () =>
        page.waitForFunction(
          () => document.querySelector("hyperframes-player")?.duration > 0,
          null,
          {
            timeout: 30000,
          },
        );
      const axe = async (root) => {
        const AxeBuilder = require("@axe-core/playwright").default;
        const found = await new AxeBuilder({ page })
          .include(root)
          .exclude("hyperframes-player")
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
          .analyze();
        return found.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`);
      };
      await open(page, "/video/builder");
      await page.getByRole("button", { name: "Product promo" }).click();
      await shot(page, "motion-pack-start");
      await page.getByRole("button", { name: "Start from Product promo" }).click();
      await ready();
      await page.getByRole("radio", { name: "Looks", exact: true }).click();
      await page.getByRole("button", { name: "Set up your brand" }).click();
      const asked = page.getByRole("dialog");
      await asked.getByLabel("Name").fill("Northbean");
      await asked
        .getByLabel("Add your logo")
        .setInputFiles(join(process.env.MOTION_FIXTURES, "can.png"));
      await asked.getByLabel("Background").fill("#123456");
      await asked.getByLabel("It fades to").fill("#0a2a4a");
      await asked.getByLabel("Accent").fill("#ff8800");
      await asked.getByLabel("What should people do at the end?").fill("Try Northbean today");
      await asked.getByLabel(/^Where/).fill("northbean.example");
      await asked.getByRole("img", { name: "Your logo" }).waitFor();
      await shot(page, "motion-pack-brand");
      seen.axeBrand = await axe("dialog");
      await asked.getByRole("button", { name: "Save your brand" }).click();
      await page
        .getByRole("checkbox", { name: "Use it in this video" })
        .waitFor({ timeout: 15000 });
      await page.waitForFunction(
        () => document.querySelector("[data-slot=scene-editor] input[type=checkbox]:checked"),
        null,
        { timeout: 15000 },
      );
      await saved();
      await page.waitForTimeout(3000);
      await shot(page, "motion-pack-branded");
      seen.axeEditor = await axe("[data-slot=scene-editor]");
      await page.getByRole("button", { name: "Make the video" }).click();
      const dialog = page.getByRole("dialog");
      for (const shape of [/^1:1/, /^16:9/, /^4:5/]) {
        await dialog.getByRole("checkbox", { name: shape }).check();
      }
      await shot(page, "motion-pack-shapes");
      seen.axeShapes = await axe("dialog");
      const started = Date.now();
      await dialog.getByRole("button", { name: "Make 4 videos" }).click();
      await dialog.getByText("Video 2 of 4", { exact: false }).waitFor({ timeout: 300000 });
      await shot(page, "motion-pack-making");
      await dialog.getByText("Your videos are in the Library").waitFor({ timeout: 900000 });
      seen.seconds = Math.round((Date.now() - started) / 1000);
      await dialog.locator("video").nth(3).waitFor();
      await page.waitForTimeout(1500);
      seen.videos = await dialog
        .locator("video")
        .evaluateAll((all) =>
          all.map((v) => [v.videoWidth, v.videoHeight, Math.round(v.duration)]),
        );
      await shot(page, "motion-pack-made");
      await dialog.getByRole("button", { name: "Close" }).click();
      // set once: a new project starts with it
      await page
        .locator("[data-slot=scene-editor]")
        .getByRole("button", { name: "Motion graphics", exact: true })
        .click();
      await page.getByRole("button", { name: "Start empty" }).click();
      await ready();
      await page.getByRole("radio", { name: "Looks", exact: true }).click();
      seen.newProjectHasBrand = await page
        .getByRole("checkbox", { name: "Use it in this video" })
        .isChecked();
      await shot(page, "motion-pack-new-project");
      console.log(`PACK ${JSON.stringify(seen)}`);
    });
  }

  if (names.has("motion-make")) {
    // The Make panel (ADR-0096 MX6): real models from inside the editor, a real voiceover with its
    // captions in time, and a real video. Run it on a throwaway DESKTOP_DATA_DIR with the real
    // models and components linked into it: what it makes stays out of the person's Library.
    await attempt("motion-make", async () => {
      const seen = { errors: [], took: {} };
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      const saved = async () => {
        await page.waitForTimeout(700);
        await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      };
      const make = async (kind, box, text, button) => {
        const started = Date.now();
        await page.getByRole("radio", { name: kind, exact: true }).click();
        await page.getByLabel(box).fill(text);
        await page.getByRole("button", { name: button }).click();
        await page.getByRole("button", { name: "Stop" }).waitFor({ timeout: 10000 });
        await page.getByRole("button", { name: button }).waitFor({ timeout: 900000 });
        seen.took[kind] = Math.round((Date.now() - started) / 1000);
        seen[`${kind}Problem`] = await page.locator("[role=alert]").allInnerTexts();
        const problem = seen[`${kind}Problem`].join(" ");
        if (problem) throw new Error(`${kind}: ${problem}`);
        await saved();
      };
      await open(page, "/video/builder");
      await page.getByRole("button", { name: "Start empty" }).click();
      await page.waitForFunction(
        () => document.querySelector("hyperframes-player")?.duration > 0,
        null,
        { timeout: 30000 },
      );
      await page.getByRole("radio", { name: "16:9" }).click();
      await page.getByRole("radio", { name: "Make", exact: true }).click();
      await shot(page, "motion-make");
      await make(
        "Picture",
        "What should it show?",
        "A red can on a marble table",
        "Make the picture",
      );
      await page.waitForTimeout(3000);
      await shot(page, "motion-make-picture");
      const WORDS =
        "Mornings are hard. Northbean steeps for eighteen hours, so you do not have to.";
      await make("Speech", "What should it say?", WORDS, "Make the voiceover");
      const frame = () => page.frames().find((f) => f.url().includes("/live/"));
      await page.waitForTimeout(3000);
      const id = (await page.locator("hyperframes-player").getAttribute("src")).match(
        /live\/([0-9a-f]{32})\./,
      )[1];
      const found = await engine(`/products/wasifyai-video/builder/projects/${id}`);
      const scene = found.slots.scenes[0];
      seen.assets = found.slots.assets.map((a) => [a.kind, a.name, a.seconds]);
      seen.sound = scene.sound;
      seen.background = scene.background?.asset;
      seen.seconds = scene.fields.seconds;
      seen.cues = scene.cues;
      seen.wordsKept = scene.cues.map((c) => c.text).join(" ") === WORDS;
      const second = scene.cues[1];
      await page
        .getByLabel("Move through the video")
        .fill(String(Math.round(((second.start + second.end) / 2) * 20) / 20));
      await page.waitForTimeout(1500);
      seen.showing = await frame().evaluate(() =>
        [...document.querySelectorAll(".cue")]
          .filter((c) => Number(getComputedStyle(c).opacity) > 0.5)
          .map((c) => c.textContent),
      );
      await shot(page, "motion-make-voiceover");
      await make(
        "Music",
        "What should it sound like?",
        "Warm acoustic guitar, unhurried",
        "Make the music",
      );
      await make(
        "Clip",
        "What should happen in it?",
        "Steam rising from a cup, slowly",
        "Make the clip",
      );
      await page.waitForTimeout(3000);
      await shot(page, "motion-make-all");
      const AxeBuilder = require("@axe-core/playwright").default;
      const axe = await new AxeBuilder({ page })
        .include("[data-slot=scene-editor]")
        .exclude("hyperframes-player")
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();
      seen.axe = axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`);
      await page.getByRole("button", { name: "Make the video" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("button", { name: "Make the video" }).click();
      await dialog.getByText("Your video is in the Library").waitFor({ timeout: 300000 });
      await shot(page, "motion-make-made");
      seen.check = await dialog.getByText(/Checked:/).innerText();
      const after = await engine(`/products/wasifyai-video/builder/projects/${id}`);
      seen.renders = (after?.renders ?? []).map((r) => [
        r.status,
        r.check?.ok,
        r.error,
        r.output_path,
      ]);
      console.log(`MOTIONMAKE ${JSON.stringify(seen)}`);
    });
  }
  if (names.has("motion-arrange")) {
    // Arranging (ADR-0096 MX4): drag a title and resize it on the real preview; the page, the document
    // and a real video must agree on where it is. Run it on a throwaway DESKTOP_DATA_DIR.
    await attempt("motion-arrange", async () => {
      const seen = { errors: [] };
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      await open(page, "/video/builder");
      await page.getByRole("button", { name: "Start empty" }).click();
      const player = page.locator("hyperframes-player");
      await page.waitForFunction(
        () => document.querySelector("hyperframes-player")?.duration > 0,
        null,
        {
          timeout: 30000,
        },
      );
      await page.getByRole("radio", { name: "16:9" }).click();
      await page.getByRole("radio", { name: "Scene 1" }).click();
      await page.getByLabel(/^Title/).fill("Moved to the corner");
      await page.getByLabel(/^A line under it/).fill("This line stays");
      await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      await page.getByRole("radio", { name: "Arrange" }).click();
      const part = page.getByRole("button", { name: /Move the title\./ });
      await part.waitFor({ timeout: 15000 });
      await page.waitForTimeout(3500);
      await shot(page, "motion-arrange-before");
      const film = await player.boundingBox();
      const from = await part.boundingBox();
      // drag it to the top left, inside the safe area
      const start = { x: from.x + from.width / 2, y: from.y + from.height / 2 };
      await page.mouse.move(start.x, start.y);
      await page.mouse.down();
      await page.mouse.move(
        film.x + film.width * 0.1 + from.width / 2,
        film.y + film.height * 0.18 + from.height / 2,
        { steps: 8 },
      );
      await page.mouse.up();
      await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      await page.waitForTimeout(3500);
      // then make it bigger with the corner
      const moved = await part.boundingBox();
      await page.mouse.move(moved.x + moved.width, moved.y + moved.height);
      await page.mouse.down();
      await page.mouse.move(moved.x + moved.width * 0.8, moved.y + moved.height, { steps: 4 });
      await page.mouse.up();
      await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      await page.waitForTimeout(3500);
      await shot(page, "motion-arrange-after");
      // arrow keys: one Undo for the lot
      await part.focus();
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("ArrowUp");
      await page.keyboard.press("ArrowUp");
      await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      await page.waitForTimeout(1500);
      const id = (await player.getAttribute("src")).match(/live\/([0-9a-f]{32})\./)[1];
      const project = await engine(`/products/wasifyai-video/builder/projects/${id}`);
      seen.document = project.slots.scenes[0].arrange;
      const frame = page.frames().find((f) => f.url().includes("/live/"));
      seen.page = await frame.evaluate(() => {
        const box = document.getElementById("root").getBoundingClientRect();
        const r = document.querySelector("[data-slot$=title]").getBoundingClientRect();
        const m = document.querySelector(".mask").getBoundingClientRect();
        const pc = (a, b) => Math.round((a / b) * 1000) / 10;
        return {
          letters: [
            pc(r.left - box.left, box.width),
            pc(r.top - box.top, box.height),
            pc(r.width, box.width),
            pc(r.height, box.height),
          ],
          mask: [
            pc(m.left - box.left, box.width),
            pc(m.top - box.top, box.height),
            pc(m.width, box.width),
            pc(m.height, box.height),
          ],
        };
      });
      const AxeBuilder = require("@axe-core/playwright").default;
      const axe = await new AxeBuilder({ page })
        .include("[data-slot=scene-editor]")
        .exclude("hyperframes-player")
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();
      seen.axe = axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`);
      await page.getByRole("button", { name: "Make the video" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("button", { name: "Make the video" }).click();
      await dialog.getByText("Your video is in the Library").waitFor({ timeout: 180000 });
      seen.video = await dialog.locator("video").getAttribute("src");
      console.log(`ARRANGE ${JSON.stringify(seen)}`);
    });
  }
  if (names.has("motion-assistant")) {
    // The assistant in the editor (ADR-0096 MX3): the real language model, from a brief to a video. It
    // leaves nothing behind: the project and its chat are deleted at the end.
    await attempt("motion-assistant", async () => {
      const seen = { errors: [], said: [] };
      page.on("pageerror", (e) => seen.errors.push(String(e)));
      const scenes = () =>
        page.locator('[aria-label="Your scenes"] [aria-label^="Scene "]').count();
      const say = async (text) => {
        const box = page.getByPlaceholder("Ask anything").last();
        await box.fill(text);
        await box.press("Enter");
      };
      const idle = async () => {
        await page.waitForTimeout(800);
        await page.waitForFunction(() => !document.querySelector("[inert]"), null, {
          timeout: 180000,
        });
        await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
        await page.waitForTimeout(4500);
        // what the player is really showing: the screen's clock, its own, and the page behind it
        seen.preview = seen.preview ?? [];
        seen.preview.push({
          clock: await page.locator("input[aria-label='Move through the video']").inputValue(),
          player: await page
            .locator("hyperframes-player")
            .evaluate((p) => [p.currentTime, p.duration, p.ready]),
          page: await Promise.all(
            page
              .frames()
              .filter((f) => f.url().includes("/live/"))
              .map((f) =>
                f.evaluate(() => ({
                  film: window.__timelines?.main?.time(),
                  shown: [...document.querySelectorAll(".scene")]
                    .filter(
                      (s) =>
                        getComputedStyle(s).visibility !== "hidden" &&
                        getComputedStyle(s).display !== "none",
                    )
                    .map((s) => [s.id, getComputedStyle(s).opacity]),
                })),
              ),
          ),
        });
      };
      await open(page, "/video/builder");
      await shot(page, "motion-start");
      await page
        .getByLabel("Describe your video")
        .fill(
          "A 20 second vertical ad for our sparkling tea, Fizzleaf. Calm, for people who want less sugar.",
        );
      const start = Date.now();
      await page.getByRole("button", { name: "Make a first version" }).click();
      await page.locator("[data-slot=scene-editor]").waitFor();
      await page.waitForFunction(
        () =>
          document.querySelectorAll('[aria-label="Your scenes"] [aria-label^="Scene "]').length > 1,
        null,
        { timeout: 180000 },
      );
      seen.firstVersionSeconds = Math.round((Date.now() - start) / 1000);
      await idle();
      seen.scenesAfterBrief = await scenes();
      seen.words = await page.locator('[aria-label="Your scenes"]').innerText();
      await shot(page, "motion-assistant");
      await say("Make this scene 3 seconds long.");
      await idle();
      seen.afterShorten = await page.locator('[aria-label="Your scenes"]').innerText();
      await say("Make a square version.");
      await idle();
      seen.shapeSquare = await page
        .getByRole("radio", { name: "1:1" })
        .getAttribute("aria-checked");
      // Undo on the change's own card
      await page.getByRole("button", { name: "Undo", exact: true }).last().click();
      await page.locator("[data-save=saved]").waitFor({ timeout: 15000 });
      seen.shapeAfterUndo = await page
        .getByRole("radio", { name: "9:16" })
        .getAttribute("aria-checked");
      await say("Add an end card that says Try Fizzleaf.");
      await idle();
      seen.scenesAfterAdd = await scenes();
      await shot(page, "motion-assistant-edits");
      await say("Add our discount to the end card.");
      await idle();
      seen.scenesAfterDiscount = await scenes();
      seen.lastAnswer = (
        await page
          .locator('[data-slot="scene-editor"] [data-role="assistant"]')
          .last()
          .innerText()
          .catch(() => "")
      ).slice(0, 300);
      await say("OK, make the video now.");
      const run = page.getByRole("button", { name: /^(Run|Make|Yes|Go ahead)/ }).last();
      await run.waitFor({ timeout: 120000 });
      await shot(page, "motion-assistant-card");
      seen.cardShown = true;
      const id = (await page.locator("hyperframes-player").getAttribute("src")).match(
        /live\/([0-9a-f]{32})\./,
      )[1];
      await run.click();
      await page.waitForTimeout(90000);
      await shot(page, "motion-assistant-made");
      const project = await engine(`/products/wasifyai-video/builder/projects/${id}`);
      seen.renders = (project?.renders ?? []).map((r) => [r.status, r.check?.ok, r.error]);
      seen.savedWords = project?.title;
      await fetch(`${BASE}/products/wasifyai-video/builder/projects/${id}`, {
        method: "DELETE",
        headers: { authorization: `Bearer ${TOKEN}` },
      });
      if (project?.conversation_id) {
        await fetch(
          `${BASE}/products/wasifyai-assistant/conversations/${project.conversation_id}`,
          {
            method: "DELETE",
            headers: { authorization: `Bearer ${TOKEN}` },
          },
        );
      }
      console.log(`MOTIONCHAT ${JSON.stringify(seen)}`);
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
      await dialog.getByRole("button", { name: "Make the video" }).click();
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
  // stage C1a of the coding agent: the coding engine set up, repaired and removed from Settings, Optional
  // parts, with the real downloads (about 0.4 GB each time). Run each on a throwaway DESKTOP_DATA_DIR.
  for (const [name, button, after] of [
    ["coding-setup", "Set up", "Repair"],
    ["coding-repair", "Repair", "Repair"],
    ["coding-remove", "Remove", "Set up"],
  ]) {
    if (scheme !== "light" || !names.has(name)) continue;
    await attempt(name, async () => {
      await open(page, "/settings");
      await page.getByRole("searchbox", { name: "Search settings" }).fill("parts");
      const row = page
        .getByRole("list", { name: "Optional parts" })
        .getByRole("listitem")
        .filter({ hasText: "Coding engine" });
      await row.waitFor();
      await shot(page, `${name}-before`, 1500);
      const began = Date.now();
      await row.getByRole("button", { name: button }).click();
      if (name === "coding-remove") {
        await page.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
      } else {
        await row.getByText("Setting up").waitFor({ timeout: 15_000 });
        await page.waitForTimeout(4000);
        await shot(page, `${name}-during`, 1500);
      }
      const failed = row.getByRole("button", { name: "Try again" });
      await Promise.race([
        row.getByRole("button", { name: after }).waitFor({ timeout: 1_200_000 }),
        failed.waitFor({ timeout: 1_200_000 }).then(async () => {
          throw new Error(`it failed: ${(await row.innerText()).replace(/\s+/g, " ")}`);
        }),
      ]);
      console.log(`${name}: ${((Date.now() - began) / 1000).toFixed(1)} s`);
      console.log(`  the row says: ${(await row.innerText()).replace(/\s+/g, " ")}`);
      await shot(page, `${name}-after`, 1500);
    });
  }
  // stage C1b of the coding agent: Code, from the first screen to an answer in Plan, with a real model
  if (scheme === "light" && names.has("code-plan")) {
    await attempt("code-plan", async () => {
      await open(page, "/code");
      await page.getByRole("button", { name: "Choose a folder" }).waitFor();
      await page.waitForTimeout(500);
      await shot(page, "code-start", 1200);
      await page.getByRole("button", { name: "Choose a folder" }).click();
      const box = page.getByRole("textbox", { name: "Ask about this project" });
      await box.waitFor();
      // a project opened here starts in "Ask me": this walk is of Plan, chosen from the pill
      await page.getByRole("button", { name: "How much the agent asks: Ask me" }).click();
      await page.getByRole("menuitemradio", { name: /^Plan/ }).click();
      await page.getByRole("button", { name: "How much the agent asks: Plan" }).waitFor();
      await shot(page, "code-session-new");
      const began = Date.now();
      await box.fill(
        "What is this project, and which file would you change to add opening hours? Keep it short.",
      );
      await box.press("Enter");
      await page.getByRole("button", { name: "Stop" }).waitFor({ timeout: 30_000 });
      await page.waitForTimeout(8000);
      await shot(page, "code-session-working");
      await page.getByText("Nothing was changed").waitFor({ timeout: 900_000 });
      console.log(`code-plan: answered in ${((Date.now() - began) / 1000).toFixed(1)} s`);
      await page.waitForTimeout(800);
      await shot(page, "code-session-plan", 1400);
      // the Files tab: a folder opened, a file read
      const tree = page.getByRole("navigation", { name: /^Files in / });
      await tree.getByRole("button", { name: "src" }).click();
      await tree.getByRole("button", { name: "pages" }).click();
      await tree.getByRole("button", { name: "home.html" }).click();
      await page.getByText(/^Read only\. \d+ lines?\.$/).waitFor();
      await shot(page, "code-session-files", 1400);
      // the session has an address of its own: it is still open after the window is loaded again
      if (!/#\/code\/[0-9a-f]{32}$/.test(page.url()))
        throw new Error(`no session in ${page.url()}`);
      await page.reload();
      await page.getByText("Nothing was changed").waitFor({ timeout: 30_000 });
      // a file found by part of its name
      await page.getByRole("searchbox", { name: "Find a file by name" }).fill("site");
      await page
        .getByRole("navigation", { name: "Files found" })
        .getByRole("button", { name: /site\.js/ })
        .click();
      await page.getByText(/^Read only\. \d+ lines?\.$/).waitFor();
      // the cost, opened
      await page.getByRole("button", { name: /^(No cost|\$\d)/ }).click();
      await page.getByRole("dialog", { name: "This session so far" }).waitFor();
      await shot(page, "code-session-find-cost", 1400);
      await page.keyboard.press("Escape");
      // the session in the Library, under its own filter
      await open(page, "/creations");
      await page.getByRole("button", { name: /Coding sessions/ }).click();
      await page
        .getByRole("link", { name: /What is this project/ })
        .first()
        .waitFor();
      await shot(page, "code-library");
      await open(page, "/code");
      await page.getByRole("heading", { name: "Projects" }).waitFor();
      await shot(page, "code-projects");
    });
  }
  // stage C2 of the coding agent: a session that changes files, with a real model. The project
  // (WASIFYAI_AUDIT_FOLDER) must have src/pages/home.html, and a .gitignore that names .env; the walk
  // reads the files on disk to see that a change, an undo and a "bring it back" really happened.
  if (scheme === "light" && names.has("code-edit")) {
    await attempt("code-edit", async () => {
      const { readFileSync, existsSync } = await import("node:fs");
      const folder = process.env.WASIFYAI_AUDIT_FOLDER ?? "";
      const home = () => readFileSync(join(folder, "src", "pages", "home.html"), "utf8");
      const env = () => readFileSync(join(folder, ".env"), "utf8");
      const [homeWas, envWas] = [home(), env()];
      await open(page, "/code");
      await page.getByRole("button", { name: "Choose a folder" }).first().waitFor();
      await page.getByRole("button", { name: "Choose a folder" }).first().click();
      const box = page.getByRole("textbox", { name: "Ask about this project" });
      await box.waitFor();
      await page.getByRole("button", { name: "How much the agent asks: Ask me" }).waitFor();
      await shot(page, "code-edit-new");
      // the mode, opened, and what the project may do
      await page.getByRole("button", { name: "How much the agent asks: Ask me" }).click();
      await page.getByRole("menu", { name: "How much the agent asks" }).waitFor();
      await shot(page, "code-edit-mode");
      await page.getByRole("menuitem", { name: /What this project may do/ }).click();
      await page.getByRole("heading", { name: /^What .* may do$/ }).waitFor();
      // an earlier walk that stopped half way may have left the kind allowed: the walk begins with it asked
      const kept = page.getByRole("button", { name: /^Remove: changing files/ });
      await page.getByRole("button", { name: /^(Allow|Remove): changing files/ }).waitFor();
      if (await kept.count()) await kept.click();
      await page.getByRole("button", { name: /^Allow: changing files/ }).waitFor();
      await shot(page, "code-edit-may");
      await page.getByRole("button", { name: "Done" }).click();
      // 1. a change to a file Undo knows: nothing is asked
      let began = Date.now();
      await box.fill(
        "In src/pages/home.html add the line <p>Open 9 to 5</p> right after the first heading. Change nothing else.",
      );
      await box.press("Enter");
      const card = page.getByRole("region", {
        name: "The agent wants to change a file Undo cannot put back",
      });
      const changed = page.getByRole("region", { name: "What this turn changed" });
      await changed.waitFor({ timeout: 900_000 });
      console.log(`code-edit: turn 1 ended after ${((Date.now() - began) / 1000).toFixed(1)} s`);
      if (!home().includes("Open 9 to 5")) throw new Error("home.html was not changed");
      if ((await card.count()) !== 0) throw new Error("a card came for a file Undo knows");
      console.log(`  the card says: ${(await changed.innerText()).replace(/\s+/g, " ")}`);
      await shot(page, "code-edit-changed", 1400);
      // 2. the Changes tab: the turn, its files, one before and after
      await changed.getByRole("button", { name: "Look at the changes" }).click();
      const pane = page.getByRole("region", { name: "Changes" });
      await pane.getByRole("navigation", { name: /^Files turn \d+ changed$/ }).waitFor();
      await pane.getByLabel(/home\.html, before and after/).waitFor();
      const files = await pane.getByRole("navigation", { name: /^Files turn/ }).innerText();
      console.log(`  the turn's files: ${files.replace(/\s+/g, " ")}`);
      await shot(page, "code-edit-changes", 1400);
      await pane.getByRole("radio", { name: "After" }).click();
      await pane.getByLabel(/home\.html, after/).waitFor();
      // 3. Undo this turn: the file on disk is byte for byte what it was
      await pane.getByRole("button", { name: "Undo this turn" }).click();
      await pane.getByText(/^Turn \d+ is undone$/).waitFor({ timeout: 60_000 });
      if (home() !== homeWas) throw new Error("undo did not put home.html back exactly");
      await page.getByRole("region", { name: "An undone turn" }).waitFor();
      await shot(page, "code-edit-undone", 1400);
      // 4. Bring it back, and undo again from the chat
      await pane.getByRole("button", { name: "Bring it back" }).click();
      await pane.getByRole("button", { name: "Undo this turn" }).waitFor({ timeout: 60_000 });
      if (!home().includes("Open 9 to 5")) throw new Error("the turn did not come back");
      await changed.getByRole("button", { name: "Undo this turn" }).click();
      await pane.getByText(/^Turn \d+ is undone$/).waitFor({ timeout: 60_000 });
      if (home() !== homeWas) throw new Error("the second undo did not put home.html back");
      // 5a. a change to a file Undo does not know: it is asked first, and a yes lets it run
      began = Date.now();
      await box.fill(
        "The shop opens on Sundays now. Change OPEN=0 to OPEN=1 in the file .env and change nothing else.",
      );
      await box.press("Enter");
      await card.getByRole("button", { name: "Yes, change it" }).waitFor({ timeout: 900_000 });
      console.log(`code-edit: asked after ${((Date.now() - began) / 1000).toFixed(1)} s`);
      if (env() !== envWas) throw new Error(".env was changed before the answer");
      await page.getByText("Waiting for you").first().waitFor();
      await shot(page, "code-edit-ask", 1300);
      await card.getByRole("button", { name: "Yes, change it" }).click();
      await card.getByText("You said yes.").waitFor({ timeout: 60_000 });
      await page
        .getByRole("button", { name: "Stop" })
        .waitFor({ state: "detached", timeout: 900_000 });
      if (!env().includes("OPEN=1")) throw new Error(".env was not changed after the yes");
      if (home() !== homeWas) throw new Error("the undone file was changed by a later turn");
      await page.getByText("This turn changed only files Undo cannot put back.").waitFor();
      // an ignored file is never among a turn's changes
      const listed = await pane.getByRole("combobox", { name: "Which turn" }).innerText();
      if (/opens on Sundays/.test(listed))
        throw new Error("a turn that changed only .env is listed");
      // 5. a no: the agent is told, the file stays, the turn goes on to its end
      began = Date.now();
      await box.fill(
        "Add the line PHONE=555-0100 at the end of the file .env and change nothing else.",
      );
      await box.press("Enter");
      const second = card.last();
      await second.getByRole("button", { name: "No", exact: true }).waitFor({ timeout: 900_000 });
      await second.getByRole("button", { name: "No", exact: true }).click();
      await second.getByText(/You said no/).waitFor({ timeout: 60_000 });
      await page
        .getByRole("button", { name: "Stop" })
        .waitFor({ state: "detached", timeout: 900_000 });
      console.log(
        `code-edit: the no, to the turn's end: ${((Date.now() - began) / 1000).toFixed(1)} s`,
      );
      if (env().includes("PHONE")) throw new Error(".env was changed after a no");
      await shot(page, "code-edit-no", 1400);
      // 6. "Allow for this project": it runs, and the next one of that kind runs with no card
      await box.fill(
        "I changed my mind: please do add the line PHONE=555-0100 at the end of the file .env.",
      );
      await box.press("Enter");
      const third = card.last();
      await third
        .getByRole("button", { name: "Allow for this project" })
        .waitFor({ timeout: 900_000 });
      await third.getByRole("button", { name: "Allow for this project" }).click();
      await third.getByText(/You allowed changing files/).waitFor({ timeout: 120_000 });
      await page
        .getByRole("button", { name: "Stop" })
        .waitFor({ state: "detached", timeout: 900_000 });
      if (!env().includes("PHONE=555-0100")) throw new Error(".env was not changed after Allow");
      const cards = await card.count();
      await box.fill("Also add the line CLOSED_ON=Monday at the end of the file .env.");
      await box.press("Enter");
      await page.getByRole("button", { name: "Stop" }).waitFor({ timeout: 60_000 });
      await page
        .getByRole("button", { name: "Stop" })
        .waitFor({ state: "detached", timeout: 900_000 });
      if (!env().includes("CLOSED_ON=Monday"))
        throw new Error(".env was not changed once the kind was allowed");
      if ((await card.count()) !== cards) throw new Error("a card came though the kind is allowed");
      // the closed line of the turn's steps says it (the same words on each step are inside, folded away)
      await page
        .locator("summary")
        .filter({ hasText: /· (1 )?allowed for this project/ })
        .last()
        .waitFor();
      await shot(page, "code-edit-allowed", 1400);
      // taken back in "What this project may do"
      await third.getByRole("button", { name: "Take it back" }).click();
      await page.getByRole("button", { name: /^Remove: changing files/ }).click();
      await page.getByRole("button", { name: /^Allow: changing files/ }).waitFor();
      await page.getByRole("button", { name: "Done" }).click();
      // 7. Stop while a card waits: within a second, and nothing is changed
      await box.fill("Add the line CITY=Marlow at the end of the file .env.");
      await box.press("Enter");
      const fourth = card.last();
      await fourth.getByRole("button", { name: "Yes, change it" }).waitFor({ timeout: 900_000 });
      began = Date.now();
      await page.getByRole("button", { name: "Stop" }).click();
      await page
        .getByText(/^You stopped this turn\./)
        .last()
        .waitFor({ timeout: 30_000 });
      console.log(
        `code-edit: Stop while the card waited: ${((Date.now() - began) / 1000).toFixed(2)} s`,
      );
      if (env().includes("CITY")) throw new Error(".env was changed though the turn was stopped");
      await fourth.getByText(/The turn ended before this was answered/).waitFor();
      await shot(page, "code-edit-stopped", 1400);
      // nothing of ours is in the project
      if (existsSync(join(folder, ".git"))) throw new Error("the project was given a .git folder");
      // the smallest window: one pane at a time, with Changes as a tab
      await page.setViewportSize({ width: 720, height: 520 });
      await page
        .getByRole("tablist", { name: "What to show" })
        .getByRole("tab", { name: "Changes" })
        .click();
      await page.waitForTimeout(500);
      await shot(page, "code-edit-changes-small");
      await page.setViewportSize({ width: 1440, height: 900 });
      await open(page, "/code");
      await page.getByRole("heading", { name: "Projects" }).waitFor();
      await shot(page, "code-edit-projects");
    });
  }
  // stage C3 of the coding agent: commands, the check and the person's terminal, with a real model. The
  // project (WASIFYAI_AUDIT_FOLDER) is a throwaway folder; the walk writes the review's case into it (an old
  // bug, a check that covers it and a function still to be added) and reads the files on disk to see what
  // really happened.
  if (scheme === "light" && names.has("code-check")) {
    await attempt("code-check", async () => {
      const { readFileSync, writeFileSync, existsSync } = await import("node:fs");
      const { execFileSync } = await import("node:child_process");
      const { homedir } = await import("node:os");
      const folder = process.env.WASIFYAI_AUDIT_FOLDER ?? "";
      const at = (name) => join(folder, name);
      const read = (name) => readFileSync(at(name), "utf8");
      const CHECK = [
        "import prices",
        "assert prices.total([]) == 0, 'total of nothing must be 0'",
        "assert prices.with_tax(100) == 120, 'with_tax is missing or wrong'",
        "print('all good')",
        "",
      ].join("\n");
      writeFileSync(at("prices.py"), "def total(xs):\n    return sum(xs) if xs else None\n");
      writeFileSync(at("check.py"), CHECK);
      writeFileSync(at("notes.txt"), "to do: the tax\n");
      const secs = (began) => ((Date.now() - began) / 1000).toFixed(1);
      await open(page, "/code");
      await page.getByRole("button", { name: "Choose a folder" }).first().waitFor();
      await page.getByRole("button", { name: "Choose a folder" }).first().click();
      const box = page.getByRole("textbox", { name: "Ask about this project" });
      await box.waitFor();
      const mine = ((await engine("/products/wasifyai-code/code/sessions?limit=200"))?.items ?? [])
        .filter((s) => s.folder.endsWith(folder.split("/").pop()))
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
      if (!mine) throw new Error("the session was not found");
      const base = `/products/wasifyai-code/code/sessions/${mine.id}`;
      const idle = () =>
        page
          .getByRole("button", { name: "Stop", exact: true })
          .waitFor({ state: "detached", timeout: 900_000 });
      const ask = async (text) => {
        await box.fill(text);
        await box.press("Enter");
      };
      // 1. the check: none yet; the dialog suggests nothing for this project, a command is typed and tried
      const word = page.getByRole("button", { name: /^The check: / });
      await word.waitFor();
      console.log(`code-check: the bar says: ${await word.innerText()}`);
      await word.click();
      const dialog = page.getByRole("dialog", { name: /^The check for / });
      await dialog.getByLabel("Command").fill("python3 -B check.py");
      await shot(page, "code-check-dialog");
      let began = Date.now();
      await dialog.getByRole("button", { name: "Try it now" }).click();
      await dialog.getByText(/Failed with exit code 1/).waitFor({ timeout: 120_000 });
      console.log(`code-check: tried at once, failed as it must (the old bug) in ${secs(began)} s`);
      await shot(page, "code-check-dialog-tried");
      await dialog.getByRole("button", { name: "Save the check" }).click();
      await dialog.waitFor({ state: "detached" });
      await page
        .getByRole("button", { name: "The check: Check failed. Change the check" })
        .waitFor();
      // 2. a question in a project whose check fails: it is answered, and no file changes
      const before = [read("prices.py"), read("check.py")];
      began = Date.now();
      await ask(
        "What does the function total in prices.py return for an empty list? Answer in one sentence and change nothing.",
      );
      await page
        .getByText(/The last check still stands: check failed/)
        .waitFor({ timeout: 900_000 });
      console.log(`code-check: a question was answered in ${secs(began)} s; no check ran`);
      if (read("prices.py") !== before[0] || read("check.py") !== before[1]) {
        throw new Error("a question changed a file");
      }
      await shot(page, "code-check-question", 1300);
      // 3. the review's case: the task adds a function, the check also covers the old bug
      began = Date.now();
      await ask(
        "Add a function with_tax(x) to prices.py that returns x * 120 // 100. Only add that function: do not run anything and do not change anything else.",
      );
      const failed = page.getByRole("region", { name: "Check failed", exact: true });
      // (the check tried by hand in the dialog left a card of its own: the round's card is the next one)
      await page.getByText("Round 2 of 3").waitFor({ timeout: 900_000 });
      console.log(
        `code-check: round 1 failed after ${secs(began)} s; the card says: ${(await failed.last().innerText()).replace(/\s+/g, " ").slice(0, 260)}`,
      );
      await shot(page, "code-check-round", 1400);
      const passed = page.getByRole("region", { name: "Check passed" });
      await passed.waitFor({ timeout: 900_000 });
      await idle();
      console.log(`code-check: one refusal, one fix, one pass, in ${secs(began)} s`);
      if (read("check.py") !== CHECK) throw new Error("the check file was touched");
      if (!read("prices.py").includes("def with_tax")) throw new Error("with_tax was not added");
      const says = execFileSync("python3", ["-B", "check.py"], { cwd: folder }).toString();
      if (!says.includes("all good")) throw new Error("the check does not pass on disk");
      const checksNow = (await engine(`${base}/check`))?.checks ?? [];
      console.log(
        `  the checks of this session, the newest first: ${checksNow.map((c) => `${c.round}:${c.result}`).join(" ")}`,
      );
      await page.getByRole("button", { name: "The check: Passed. Change the check" }).waitFor();
      await shot(page, "code-check-passed", 1500);
      // 4. a check of two minutes: the screen stays live and every other call answers within a second
      await word.click();
      await dialog.getByLabel("Command").fill("sleep 120; python3 -B check.py");
      await dialog.getByRole("button", { name: "Save the check" }).click();
      await dialog.waitFor({ state: "detached" });
      await ask(
        "Add the comment line '# prices' at the very top of prices.py. Do not run anything and change nothing else.",
      );
      const running = page.getByRole("region", { name: "The check is running" });
      await running.waitFor({ timeout: 900_000 });
      began = Date.now();
      await shot(page, "code-check-running", 1400);
      let slowest = 0;
      let calls = 0;
      while ((await running.count()) && Date.now() - began < 150_000) {
        for (const path of ["", "/turns", "/changes", "/check", "/files?path="]) {
          const t = Date.now();
          if ((await engine(`${base}${path}`)) === null) throw new Error(`no answer from ${path}`);
          slowest = Math.max(slowest, Date.now() - t);
          calls += 1;
        }
        // and the screen answers: the Files tab opens and lists the project
        await page
          .getByRole("tablist", { name: "Beside the chat" })
          .getByRole("tab", { name: "Files" })
          .click();
        await page
          .getByRole("region", { name: "Files" })
          .getByText("prices.py")
          .first()
          .waitFor({ timeout: 2000 });
        await page.waitForTimeout(5000);
      }
      await passed.last().waitFor({ timeout: 60_000 });
      await idle();
      console.log(
        `code-check: a check of ${secs(began)} s ran; ${calls} other calls, the slowest ${slowest} ms`,
      );
      if (slowest >= 1000) throw new Error("a call took a second or more while the check ran");
      // 5. Stop during a check: within a second, and nothing is left running
      await ask(
        "Change the comment at the top of prices.py to '# the prices'. Do not run anything and change nothing else.",
      );
      await running.waitFor({ timeout: 900_000 });
      await page.waitForTimeout(3000);
      began = Date.now();
      await running.getByRole("button", { name: "Stop the check" }).click();
      await page.getByRole("region", { name: "Not checked" }).waitFor({ timeout: 30_000 });
      const stopMs = Date.now() - began;
      await idle();
      await page.waitForTimeout(700);
      let left = "";
      try {
        left = execFileSync("pgrep", ["-fl", "sleep 120"]).toString();
      } catch {
        left = ""; // pgrep found nothing
      }
      console.log(
        `code-check: Stop during a check: ${stopMs} ms; left running: ${left.trim() || "nothing"}`,
      );
      if (stopMs >= 1000) throw new Error("Stop during a check took a second or more");
      if (left.trim()) throw new Error("the check left a process behind");
      await shot(page, "code-check-stopped", 1400);
      // 6. a check that cannot pass: three rounds, then "needs you"
      await word.click();
      await dialog
        .getByLabel("Command")
        .fill("python3 -B check.py && echo 'this check can never pass' && exit 1");
      await dialog.getByRole("button", { name: "Save the check" }).click();
      await dialog.waitFor({ state: "detached" });
      began = Date.now();
      await ask(
        "Change the comment at the top of prices.py to '# all prices'. Do not run anything.",
      );
      const needs = page.getByRole("region", { name: "Check failed · needs you" });
      await needs.waitFor({ timeout: 1_500_000 });
      await idle();
      console.log(
        `code-check: needs you after ${secs(began)} s; the card says: ${(await needs.innerText()).replace(/\s+/g, " ").slice(0, 300)}`,
      );
      const rounds = ((await engine(`${base}/turns`))?.items ?? []).at(-1);
      console.log(
        `  the turn: result ${rounds?.result}, ${rounds?.rounds} rounds, why ${rounds?.check_why}`,
      );
      await page
        .getByRole("button", { name: "The check: Check failed · needs you. Change the check" })
        .waitFor();
      await shot(page, "code-check-needs-you", 1700);
      // 7. the person's terminal: inside the same protected area
      await word.click();
      await dialog.getByLabel("Command").fill("python3 -B check.py");
      await dialog.getByRole("button", { name: "Save the check" }).click();
      await dialog.waitFor({ state: "detached" });
      await page
        .getByRole("tablist", { name: "Beside the chat" })
        .getByRole("tab", { name: "Terminal" })
        .click();
      const term = page.getByRole("region", { name: "Terminal" });
      await term.getByRole("button", { name: "Open a terminal" }).click();
      const screenOf = term.locator(".xterm-rows");
      await screenOf.waitFor({ timeout: 30_000 });
      const type = async (line, until) => {
        await term.locator(".xterm").click();
        await page.keyboard.type(line);
        await page.keyboard.press("Enter");
        await page.waitForFunction(
          ([sel, text]) =>
            (document.querySelector(sel)?.textContent ?? "").replace(/\u00a0/g, " ").includes(text),
          [".xterm-rows", until],
          { timeout: 60_000 },
        );
      };
      await type("python3 -B check.py; echo ran-$((40+2))", "ran-42");
      // (`~` is the protected area's own home in this terminal: the person's real one is named in full)
      await type(`ls ${homedir()} > /dev/null 2>&1; echo home-$?-`, "home-");
      await type("echo x > ../outside-by-the-terminal.txt; echo out-$?-", "out-");
      await type("ps > /dev/null 2>&1; echo ps-$?-", "ps-");
      const shown = ((await screenOf.textContent()) ?? "").replace(/\u00a0/g, " ");
      console.log(`code-check: the terminal showed: ${shown.replace(/\s+/g, " ").slice(-420)}`);
      for (const [mark, what] of [
        ["home-0-", "read the home folder"],
        ["out-0-", "wrote outside the project"],
        ["ps-0-", "ran ps"],
      ]) {
        if (shown.includes(mark)) throw new Error(`the terminal ${what}`);
      }
      if (existsSync(join(folder, "..", "outside-by-the-terminal.txt")))
        throw new Error("a file was written outside");
      await shot(page, "code-check-terminal", 1100);
      // 8. a command that deletes is asked first in "Ask me"; a yes runs it, and Undo brings the file back
      began = Date.now();
      await ask("Delete the file notes.txt with the command rm notes.txt. Do nothing else.");
      const del = page.getByRole("region", { name: "The agent wants to delete files" });
      await del.getByRole("button", { name: "Yes, run it" }).waitFor({ timeout: 900_000 });
      console.log(
        `code-check: asked before the delete after ${secs(began)} s: ${(await del.locator("code").first().innerText()).trim()}`,
      );
      if (!existsSync(at("notes.txt"))) throw new Error("notes.txt was deleted before the answer");
      await shot(page, "code-check-ask-delete", 1500);
      await del.getByRole("button", { name: "Yes, run it" }).click();
      await idle();
      if (existsSync(at("notes.txt"))) throw new Error("notes.txt is still there after the yes");
      const changedCard = page.getByRole("region", { name: "What this turn changed" }).last();
      await changedCard.getByRole("button", { name: "Undo this turn" }).click();
      await page
        .getByRole("region", { name: "An undone turn" })
        .last()
        .waitFor({ timeout: 60_000 });
      if (read("notes.txt") !== "to do: the tax\n")
        throw new Error("Undo did not bring notes.txt back");
      console.log("code-check: the delete ran after the yes, and Undo brought the file back");
      // 9. the agent may make a repository when asked; opening the project did not
      if (existsSync(at(".git"))) throw new Error("the project has a .git it was not asked for");
      await ask(
        "Run git init in this project so that it becomes a git repository. Do nothing else.",
      );
      await idle();
      console.log(
        `code-check: after "run git init": .git ${existsSync(at(".git")) ? "is there" : "is NOT there"}`,
      );
      if (!existsSync(at(".git"))) throw new Error("the agent could not make a repository");
      await page.setViewportSize({ width: 720, height: 520 });
      await page
        .getByRole("tablist", { name: "What to show" })
        .getByRole("tab", { name: "Terminal" })
        .click();
      await page.waitForTimeout(800);
      await shot(page, "code-check-terminal-small");
      await page.setViewportSize({ width: 1440, height: 900 });
    });
  }
  // stage C4 of the coding agent: a new project from the starter, its preview, and the gate's request ("a
  // to-do web app with a logo") built by a real model, with the logo made by Wasify AI's own picture product.
  // WASIFYAI_AUDIT_FOLDER is an empty throwaway folder the project is made in. Node comes from the optional
  // part alone; the results are read back from disk and from the running page.
  if (scheme === "light" && names.has("code-build")) {
    await attempt("code-build", async () => {
      const { readFileSync, existsSync, statSync } = await import("node:fs");
      const parent = process.env.WASIFYAI_AUDIT_FOLDER ?? "";
      const folder = join(parent, "todo-app");
      const at = (name) => join(folder, name);
      const secs = (began) => ((Date.now() - began) / 1000).toFixed(1);
      await open(page, "/code");
      await page.getByRole("button", { name: "Start in a new, empty folder" }).first().click();
      const dialog = page.getByRole("dialog", { name: "Start in a new, empty folder" });
      await dialog.getByText("A small web app").waitFor();
      await dialog.getByLabel("The project’s name").fill("todo-app");
      await dialog.getByRole("button", { name: "Choose a folder" }).click();
      await dialog.getByText(/todo-app$/).waitFor();
      await shot(page, "code-build-new");
      await dialog.getByRole("button", { name: "Make the project" }).click();
      const box = page.getByRole("textbox", { name: "Ask about this project" });
      await box.waitFor({ timeout: 60_000 });
      for (const name of [
        "package.json",
        "index.html",
        "src/logic.js",
        "tests/logic.test.js",
        "dev-server.mjs",
      ]) {
        if (!existsSync(at(name))) throw new Error(`the starter did not write ${name}`);
      }
      console.log(`code-build: the starter is in ${folder}`);
      const idle = () =>
        page
          .getByRole("region", { name: "Chat" })
          .getByRole("button", { name: "Stop", exact: true })
          .waitFor({ state: "detached", timeout: 2_400_000 });
      // 1. the preview of the untouched starter
      const tabs = page.getByRole("tablist", { name: "Beside the chat" });
      await tabs.getByRole("tab", { name: "Preview" }).click();
      const pane = page.getByRole("region", { name: "Preview" });
      let began = Date.now();
      await pane.getByRole("button", { name: "Start the preview" }).click();
      const frame = page.frameLocator('iframe[title="The preview of todo-app"]');
      await frame.getByRole("heading", { name: "todo-app" }).waitFor({ timeout: 60_000 });
      console.log(
        `code-build: the starter's page was shown ${secs(began)} s after "Start the preview"; the bar says: ${(await pane.locator("output").first().innerText()).trim()}, ${(await pane.getByText(/port \d+/).innerText()).replace(/\s+/g, " ")}`,
      );
      if (
        (await pane.getByText("Other computers on your network can open this too").count()) !== 0
      ) {
        throw new Error("the starter's preview listens to more than this computer");
      }
      await shot(page, "code-build-preview-starter", 1000);
      // 2. the check that came with the starter, tried by hand
      await page.getByRole("button", { name: /^The check: / }).click();
      const check = page.getByRole("dialog", { name: /^The check for / });
      began = Date.now();
      await check.getByRole("button", { name: "Try it now" }).click();
      await check.getByText(/^Passed in /).waitFor({ timeout: 120_000 });
      console.log(
        `code-build: the starter's own check (npm test) passed inside the protected area: ${(await check.getByText(/^Passed in /).innerText()).trim()}`,
      );
      await check.getByRole("button", { name: "Cancel" }).click();
      // 3. the gate's request
      began = Date.now();
      await box.fill(
        "Build a to-do web app in this project. The page has a text box and an Add button. Below is the list of to-dos; each has a checkbox that marks it done and a Remove button. Keep the to-dos in localStorage so they survive a reload. Put the list's logic in src/logic.js as pure functions and test them in tests/logic.test.js. Give the page a logo at the top: ask Wasify AI for a picture of a simple checklist logo saved as assets/logo.png, and show it with an img tag. Give the text box the placeholder 'What needs doing?'.",
      );
      await box.press("Enter");
      const card = page.getByRole("region", {
        name: "The agent wants Wasify AI to make a picture or speech",
      });
      await card.getByRole("button", { name: "Yes, make it" }).waitFor({ timeout: 2_400_000 });
      console.log(
        `code-build: asked before the picture after ${secs(began)} s: ${(await card.locator("code").first().innerText()).trim()}`,
      );
      if (existsSync(at("assets/logo.png")))
        throw new Error("the logo was there before the answer");
      await shot(page, "code-build-ask-picture", 1500);
      const asked = Date.now();
      await card.getByRole("button", { name: "Yes, make it" }).click();
      await card.getByText("You said yes.").waitFor({ timeout: 2_400_000 });
      console.log(`code-build: the picture step ended ${secs(asked)} s after the yes`);
      // the agent may ask again before it is done (it tidies up what it started): each card is answered yes
      const chat = page.getByRole("region", { name: "Chat" });
      let others = 0;
      for (;;) {
        const more = chat.getByRole("button", { name: /^Yes, (run|change|make) it$/ });
        const stopBtn = chat.getByRole("button", { name: "Stop", exact: true });
        if ((await stopBtn.count()) === 0) break;
        if ((await more.count()) > 0 && (await more.first().isEnabled())) {
          const what = await chat.locator("section code").last().innerText();
          console.log(`  asked again, answered yes: ${what.trim().slice(0, 160)}`);
          await more.first().click();
          others += 1;
        }
        if (Date.now() - began > 2_400_000) throw new Error("the turn did not end in 40 minutes");
        await page.waitForTimeout(1500);
      }
      console.log(
        `code-build: the turn ended after ${secs(began)} s, with ${others} more question(s)`,
      );
      // what is on disk
      if (!existsSync(at("assets/logo.png"))) throw new Error("there is no assets/logo.png");
      const logo = readFileSync(at("assets/logo.png"));
      const png = logo.subarray(0, 8).toString("hex") === "89504e470d0a1a0a";
      console.log(
        `  assets/logo.png: ${statSync(at("assets/logo.png")).size} bytes, ${png ? "a PNG" : "NOT a PNG"}, ${logo.readUInt32BE(16)} by ${logo.readUInt32BE(20)}`,
      );
      if (!png || logo.length < 10_000) throw new Error("the logo is not a real picture");
      const word = await page.getByRole("button", { name: /^The check: / }).innerText();
      const last = ((await engine("/products/wasifyai-code/code/sessions?limit=200"))?.items ?? [])
        .filter((x) => x.folder.endsWith("todo-app"))
        .sort((x, y) => (x.created_at < y.created_at ? 1 : -1))[0];
      const turns =
        (await engine(`/products/wasifyai-code/code/sessions/${last.id}/turns`))?.items ?? [];
      const t = turns.at(-1);
      console.log(
        `  the bar says: ${word.trim()}; the turn: result ${t?.result}, ${t?.rounds} rounds, ${t?.changed} files changed, ${t?.steps} steps, ended ${t?.why}`,
      );
      await shot(page, "code-build-done", 1800);
      // 4. the running result, used
      await tabs.getByRole("tab", { name: "Preview" }).click();
      const input = frame.getByPlaceholder("What needs doing?");
      await input.waitFor({ timeout: 60_000 });
      await input.fill("Buy bread");
      await frame.getByRole("button", { name: /add/i }).first().click();
      await frame.getByText("Buy bread").first().waitFor({ timeout: 10_000 });
      const shown = await frame
        .locator("img")
        .first()
        .evaluate((img) => img.complete && img.naturalWidth > 0);
      console.log(
        `  in the preview: "Buy bread" was added to the list; the logo ${shown ? "is shown" : "is NOT shown"}`,
      );
      await page.waitForTimeout(600);
      await shot(page, "code-build-preview", 1000);
      if (!shown) throw new Error("the logo is not shown in the running app");
      // it survives a reload, as asked
      await pane.getByRole("button", { name: "Load again" }).click();
      await frame.getByText("Buy bread").first().waitFor({ timeout: 15_000 });
      console.log("  after loading the page again the to-do is still there");
      await pane.getByRole("button", { name: "Phone" }).click();
      await page.waitForTimeout(600);
      await shot(page, "code-build-preview-phone", 1000);
      if (t?.result !== "passed") throw new Error(`the turn's check did not pass: ${t?.result}`);
      await pane.getByRole("button", { name: "Stop" }).click();
      await pane.getByText("Nothing is running yet").waitFor({ timeout: 20_000 });
    });
  }
  // stage X2 of the coding agent: Extensions, with a real model. WASIFYAI_AUDIT_FOLDER is an empty throwaway
  // folder; the walk makes a small project and a skill of the person's own in it. What "a skill fired" means
  // here: the chat says which skill the message switched on, and for the person's own skill the answer
  // follows a rule only that skill gives.
  if (scheme === "light" && names.has("code-extensions")) {
    await attempt("code-extensions", async () => {
      const { mkdirSync, writeFileSync, existsSync } = await import("node:fs");
      const top = process.env.WASIFYAI_AUDIT_FOLDER ?? "";
      const project = join(top, "bakery-site");
      const mine = join(top, "house-style");
      mkdirSync(project, { recursive: true });
      mkdirSync(mine, { recursive: true });
      writeFileSync(
        join(project, "index.html"),
        "<h1>Bakery</h1>\n<p>A loaf costs 4 pounds.</p>\n",
      );
      writeFileSync(
        join(project, "login.js"),
        "export function login(user, password) {\n  return password === 'bread';\n}\n",
      );
      writeFileSync(
        join(mine, "SKILL.md"),
        "---\nname: house-style\ndescription: How this shop's pages and answers are worded.\ntriggers:\n  - price\n  - prices\n---\n\n# House style\n\nWhenever you answer a question about prices, end your final answer with this line, exactly, on a line of its own:\n\nBaked fresh every morning.\n",
      );
      const pick = (folder) =>
        page.evaluate((f) => {
          window.__wasifyAuditFolder = f;
        }, folder);
      const secs = (began) => ((Date.now() - began) / 1000).toFixed(1);
      // a project, in Plan: the skills here are text, and a session that only reads shows them best
      await open(page, "/code");
      await pick(project);
      await page.getByRole("button", { name: "Choose a folder" }).first().click();
      const box = page.getByRole("textbox", { name: "Ask about this project" });
      await box.waitFor();
      const sessionHash = await page.evaluate(() => window.location.hash);
      const chat = page.getByRole("region", { name: "Chat" });
      const idle = () =>
        chat
          .getByRole("button", { name: "Stop", exact: true })
          .waitFor({ state: "detached", timeout: 900_000 });
      const ask = async (text) => {
        await box.fill(text);
        await box.press("Enter");
        await chat
          .getByRole("button", { name: "Stop", exact: true })
          .waitFor({ timeout: 60_000 })
          .catch(() => {});
        await idle();
      };
      const lastTurn = () => chat.getByRole("article").last();
      const usedIn = async (turn) =>
        (await turn.getByText(/^Using the skills? /).count())
          ? (
              await turn
                .getByText(/^Using the skills? /)
                .first()
                .innerText()
            ).trim()
          : "no skill";
      // 1. the list, for this project
      await open(page, "/extensions");
      await page.getByRole("heading", { name: "Extensions" }).waitFor();
      await page
        .getByRole("switch", { name: "Explain in plain words: on for bakery-site" })
        .waitFor({ timeout: 30_000 });
      const rows = await page.getByRole("listitem").allInnerTexts();
      console.log(
        `code-extensions: ${rows.length} offered: ${rows.map((r) => r.split("\n")[0]).join(" | ")}`,
      );
      await shot(page, "code-extensions-list", 1100);
      // 2. a public skill's text, read before it is switched on
      await page.getByRole("button", { name: "Details of Security" }).click();
      const detail = page.getByRole("dialog", { name: "Security" });
      await detail.getByText("This text was not written by Wasify AI").waitFor();
      const lines = await detail.getByText(/^SKILL\.md · \d+ lines/).innerText();
      console.log(`code-extensions: the public skill "Security" shows its text: ${lines}`);
      await shot(page, "code-extensions-detail", 1300);
      await detail.getByRole("button", { name: "Done" }).click();
      // 3. one of ours fires in a real session
      await page.evaluate((h) => {
        window.location.hash = h;
      }, sessionHash);
      await box.waitFor();
      let began = Date.now();
      await ask("Explain this project in plain words, in three sentences.");
      let used = await usedIn(lastTurn());
      console.log(`code-extensions: turn 1 (${secs(began)} s): ${used}`);
      if (!/Explain in plain words/.test(used)) throw new Error("our own skill did not fire");
      await shot(page, "code-extensions-ours", 1200);
      // 4. ours off, a public one on: ours stops, the public one fires
      await open(page, "/extensions");
      await page
        .getByRole("switch", { name: "Explain in plain words: on for bakery-site" })
        .click();
      await page
        .getByRole("switch", { name: "Explain in plain words: off for bakery-site" })
        .waitFor();
      await page.getByRole("switch", { name: "Security: off for bakery-site" }).click();
      await page.getByRole("switch", { name: "Security: on for bakery-site" }).waitFor();
      await shot(page, "code-extensions-switched", 1100);
      await page.evaluate((h) => {
        window.location.hash = h;
      }, sessionHash);
      await box.waitFor();
      began = Date.now();
      await ask(
        "Explain in plain words whether the login in login.js is a security risk, in two sentences.",
      );
      used = await usedIn(lastTurn());
      console.log(`code-extensions: turn 2 (${secs(began)} s), ours off and Security on: ${used}`);
      if (/Explain in plain words/.test(used))
        throw new Error("the skill that was switched off still fired");
      if (!/Security/.test(used)) throw new Error("the public skill did not fire");
      await shot(page, "code-extensions-public", 1300);
      // 5. a skill of the person's own, from a folder
      await open(page, "/extensions");
      await page.getByRole("button", { name: "Add from a folder" }).waitFor();
      await pick(mine);
      await page.getByRole("button", { name: "Add from a folder" }).click();
      const add = page.getByRole("dialog", { name: "Add an extension from a folder" });
      await add.getByText(/Found a skill: “House style”/).waitFor();
      await shot(page, "code-extensions-add", 1300);
      await add.getByRole("button", { name: "Add the skill" }).click();
      await page
        .getByRole("switch", { name: "House style: on for bakery-site" })
        .waitFor({ timeout: 30_000 });
      await page.evaluate((h) => {
        window.location.hash = h;
      }, sessionHash);
      await box.waitFor();
      began = Date.now();
      await ask("What are the prices in this project? Answer in one sentence.");
      used = await usedIn(lastTurn());
      const answer = (await lastTurn().innerText()).replace(/\s+/g, " ");
      const followed = answer.includes("Baked fresh every morning.");
      console.log(
        `code-extensions: turn 3 (${secs(began)} s), the person's own skill: ${used}; its rule ${followed ? "was followed" : "was NOT followed"}: …${answer.slice(-170)}`,
      );
      if (!/House style/.test(used)) throw new Error("the added skill did not fire");
      if (!followed) throw new Error("the added skill's rule was not followed");
      await shot(page, "code-extensions-added", 1300);
      // 6. removed: our copy goes, the person's folder stays
      await open(page, "/extensions");
      await page.getByRole("button", { name: "Details of House style" }).click();
      const own = page.getByRole("dialog", { name: "House style" });
      await own.getByRole("button", { name: "Remove" }).click();
      await page
        .getByRole("dialog", { name: "Remove House style?" })
        .getByRole("button", { name: "Remove" })
        .click();
      await page
        .getByRole("button", { name: "Details of House style" })
        .waitFor({ state: "detached", timeout: 30_000 });
      if (!existsSync(join(mine, "SKILL.md")))
        throw new Error("the person's own folder was touched");
      console.log("code-extensions: the added skill was removed; the person's folder is as it was");
      await page.setViewportSize({ width: 720, height: 700 });
      await page.waitForTimeout(500);
      await shot(page, "code-extensions-small");
      await page.setViewportSize({ width: 1440, height: 900 });
    });
  }
  // stage C6 with X3 of the coding agent: Scheduled and a plugin, with a real model. WASIFYAI_AUDIT_FOLDER
  // is an empty throwaway folder; the walk makes a small project with a failing check and a plugin with a
  // hook in it. A schedule is made from a template and run now: the run works on a copy, the project is
  // read back from disk untouched, and the change arrives only with "Apply to the project".
  if (scheme === "light" && names.has("code-scheduled")) {
    await attempt("code-scheduled", async () => {
      const { mkdirSync, writeFileSync, readFileSync, existsSync } = await import("node:fs");
      const top = process.env.WASIFYAI_AUDIT_FOLDER ?? "";
      const project = join(top, "bakery-site");
      const plugin = join(top, "work-log");
      mkdirSync(project, { recursive: true });
      mkdirSync(join(plugin, ".plugin"), { recursive: true });
      mkdirSync(join(plugin, "hooks"), { recursive: true });
      mkdirSync(join(plugin, "skills", "log-style"), { recursive: true });
      const BUG = "def total(xs):\n    return sum(xs) if xs else None\n";
      writeFileSync(join(project, "prices.py"), BUG);
      writeFileSync(
        join(project, "check.py"),
        "import prices\nassert prices.total([]) == 0, 'total of nothing must be 0'\nprint('all good')\n",
      );
      writeFileSync(join(project, "notes.txt"), "to do: the tax\n");
      writeFileSync(
        join(plugin, ".plugin", "plugin.json"),
        JSON.stringify(
          {
            name: "work-log",
            version: "1.0.0",
            description: "Keeps a log of the agent's steps in the project.",
          },
          null,
          2,
        ),
      );
      writeFileSync(
        join(plugin, "hooks", "hooks.json"),
        JSON.stringify({
          hooks: {
            UserPromptSubmit: [
              { hooks: [{ type: "command", command: "echo asked >> work-log.txt" }] },
            ],
          },
        }),
      );
      writeFileSync(
        join(plugin, "skills", "log-style", "SKILL.md"),
        "---\nname: log-style\ndescription: How the work log is worded.\ntriggers:\n  - work log\n---\n\nKeep log lines short.\n",
      );
      const pick = (folder) =>
        page.evaluate((f) => {
          window.__wasifyAuditFolder = f;
        }, folder);
      const secs = (began) => ((Date.now() - began) / 1000).toFixed(1);
      const read = (name) => readFileSync(join(project, name), "utf8");
      // a project with a check that fails for an old bug
      await open(page, "/code");
      await pick(project);
      await page.getByRole("button", { name: "Choose a folder" }).first().click();
      const box = page.getByRole("textbox", { name: "Ask about this project" });
      await box.waitFor();
      const sessionHash = await page.evaluate(() => window.location.hash);
      const word = page.getByRole("button", { name: /^The check: / });
      await word.click();
      const dialog = page.getByRole("dialog", { name: /^The check for / });
      await dialog.getByLabel("Command").fill("python3 -B check.py");
      await dialog.getByRole("button", { name: "Save the check" }).click();
      await dialog.waitFor({ state: "detached" });
      // 1. the empty list
      await open(page, "/scheduled");
      await page.getByRole("heading", { name: "Scheduled" }).waitFor();
      await page.getByText("No schedules yet").waitFor({ timeout: 30_000 });
      await shot(page, "code-scheduled-empty", 1000);
      // 2. a schedule from a template
      await page.getByRole("button", { name: "New schedule" }).click();
      await page.getByRole("heading", { name: "New schedule" }).waitFor();
      await page.getByRole("button", { name: "Check it every night" }).waitFor({ timeout: 30_000 });
      const chips = await page
        .getByText("Or start from a template:")
        .locator("..")
        .getByRole("button")
        .allInnerTexts();
      console.log(`code-scheduled: templates offered: ${chips.join(" | ")}`);
      await page.getByRole("button", { name: "Check it every night" }).click();
      const asked = await page.getByLabel("What should be done").inputValue();
      console.log(`code-scheduled: the template's request: ${asked.slice(0, 120)}…`);
      await shot(page, "code-scheduled-new", 1900);
      await page.getByRole("button", { name: "Save the schedule" }).click();
      await page
        .getByRole("button", { name: "Run Check it every night now" })
        .waitFor({ timeout: 30_000 });
      const row = (await page.getByRole("listitem").first().innerText()).replace(/\s+/g, " ");
      console.log(`code-scheduled: the list says: ${row.slice(0, 220)}`);
      await shot(page, "code-scheduled-list", 1000);
      // 3. Run now: a real run on a copy
      const before = [read("prices.py"), read("check.py"), read("notes.txt")];
      let began = Date.now();
      await page.getByRole("button", { name: "Run Check it every night now" }).click();
      await page.getByText("Running now").waitFor({ timeout: 60_000 });
      await shot(page, "code-scheduled-running", 1000);
      await page.getByText("Running now").waitFor({ state: "detached", timeout: 1_500_000 });
      const after = (await page.getByRole("listitem").first().innerText()).replace(/\s+/g, " ");
      console.log(`code-scheduled: the run ended after ${secs(began)} s: ${after.slice(0, 260)}`);
      if (
        read("prices.py") !== before[0] ||
        read("check.py") !== before[1] ||
        read("notes.txt") !== before[2]
      )
        throw new Error("the run changed the project itself");
      console.log("code-scheduled: the project's files are byte for byte what they were");
      await shot(page, "code-scheduled-ran", 1000);
      // 4. its history, the changes, and applying them
      await page.getByRole("button", { name: "History of Check it every night" }).click();
      await page.getByText(/Your project has not been touched/).waitFor({ timeout: 30_000 });
      await shot(page, "code-scheduled-history", 1200);
      await page.getByRole("button", { name: "Look at the changes" }).click();
      const changes = page.getByRole("dialog", { name: "What the run changed" });
      await changes.getByText("prices.py").waitFor();
      console.log(
        `code-scheduled: the run changed: ${(await changes.getByRole("listitem").allInnerTexts()).map((t) => t.replace(/\s+/g, " ")).join(" | ")}`,
      );
      await shot(page, "code-scheduled-changes", 1200);
      await changes.getByRole("button", { name: "Apply to the project" }).click();
      await page.getByText(/written into the project/).waitFor({ timeout: 60_000 });
      const fixed = read("prices.py");
      console.log(`code-scheduled: applied; prices.py is now: ${fixed.replace(/\n/g, " ⏎ ")}`);
      if (fixed === BUG) throw new Error("applying did not write the change into the project");
      if (read("check.py") !== before[1]) throw new Error("the check file was changed");
      await shot(page, "code-scheduled-applied", 1200);
      // 5. paused: no next time
      await page.getByRole("switch", { name: "Check it every night: on" }).click();
      await page.getByText("Off. It will not run.").waitFor({ timeout: 30_000 });
      // 6. a plugin with a hook: refused until approved
      await open(page, "/extensions");
      await page.getByRole("button", { name: "Add from a folder" }).waitFor();
      await pick(plugin);
      await page.getByRole("button", { name: "Add from a folder" }).click();
      const add = page.getByRole("dialog", { name: "Add an extension from a folder" });
      await add.getByText(/Found a plugin: “Work log”/).waitFor();
      await add.getByText("It stays off until you approve it").waitFor();
      await shot(page, "code-plugin-add", 1400);
      await add.getByRole("button", { name: "Add the plugin" }).click();
      await page.getByRole("button", { name: "Look and switch on" }).waitFor({ timeout: 30_000 });
      if (await page.getByRole("switch", { name: /^Work log/ }).count())
        throw new Error("a plugin that is not approved has a switch");
      await shot(page, "code-plugin-list", 1100);
      // not approved: a message runs no hook
      await page.evaluate((h) => {
        window.location.hash = h;
      }, sessionHash);
      await box.waitFor();
      const chat = page.getByRole("region", { name: "Chat" });
      const ask = async (text) => {
        await box.fill(text);
        await box.press("Enter");
        await chat
          .getByRole("button", { name: "Stop", exact: true })
          .waitFor({ timeout: 60_000 })
          .catch(() => {});
        await chat
          .getByRole("button", { name: "Stop", exact: true })
          .waitFor({ state: "detached", timeout: 900_000 });
      };
      // (the session is in "Ask me", as a project opened here starts: a session that only reads, in Plan,
      // is given no hook at all)
      began = Date.now();
      await ask("In one sentence: what does prices.py do? Change nothing.");
      if (existsSync(join(project, "work-log.txt")))
        throw new Error("a hook ran before the plugin was approved");
      console.log(
        `code-scheduled: plugin not approved, a turn ran (${secs(began)} s) and no hook did`,
      );
      // approved and switched on: the hook runs
      await open(page, "/extensions");
      await page.getByRole("button", { name: "Look and switch on" }).click();
      const detail = page.getByRole("dialog", { name: "Work log" });
      await detail.getByText("This plugin brings more than text").waitFor();
      await shot(page, "code-plugin-approve", 1500);
      await detail.getByRole("button", { name: "Approve what it brings" }).click();
      await detail.getByText("You approved what it brings.").waitFor({ timeout: 30_000 });
      await detail.getByRole("switch", { name: "Work log: off for bakery-site" }).first().click();
      await detail.getByRole("switch", { name: "Work log: on for bakery-site" }).first().waitFor();
      await shot(page, "code-plugin-approved", 1500);
      await detail.getByRole("button", { name: "Done" }).click();
      await page.evaluate((h) => {
        window.location.hash = h;
      }, sessionHash);
      await box.waitFor();
      began = Date.now();
      await ask("In one sentence: what does check.py check? Change nothing.");
      const log = existsSync(join(project, "work-log.txt")) ? read("work-log.txt") : "";
      console.log(
        `code-scheduled: plugin approved and on, a turn ran (${secs(began)} s); work-log.txt holds: ${JSON.stringify(log)}`,
      );
      if (!log.includes("asked")) throw new Error("the approved plugin's hook did not run");
      await page.setViewportSize({ width: 720, height: 700 });
      await open(page, "/scheduled");
      await page.getByRole("heading", { name: "Scheduled" }).waitFor();
      await page.waitForTimeout(800);
      await shot(page, "code-scheduled-small");
      await page.setViewportSize({ width: 1440, height: 900 });
    });
  }
  // the Browser tab's own bar and the stay-open switch, as far as a browser can show them: the pages
  // themselves are a second webview of the real shell, which this walk does not have (the shell tests that
  // itself: WASIFYAI_BROWSER_TEST and WASIFYAI_STAY_TEST, docs/spikes/coding-browser.md)
  if (scheme === "light" && names.has("code-browser")) {
    await attempt("code-browser", async () => {
      await open(page, "/code");
      await page.getByRole("button", { name: "Choose a folder" }).first().click();
      await page.getByRole("textbox", { name: "Ask about this project" }).waitFor();
      const tabs = page.getByRole("tablist", { name: "Beside the chat" });
      await tabs.getByRole("tab", { name: "Browser" }).click();
      const pane = page.getByRole("region", { name: "Browser" });
      await pane.getByText("A browser of your own").waitFor();
      await pane.getByLabel("An address, or words to search for").fill("date getDay javascript");
      await shot(page, "code-browser-tab", 1000);
      await open(page, "/scheduled");
      const stays = page.getByRole("switch", {
        name: "Open Wasify AI when I log in, and keep it in the menu bar",
      });
      await stays.waitFor({ timeout: 30_000 });
      await stays.click();
      await page.getByText(/Quit it from its item in the menu bar/).waitFor();
      await shot(page, "code-scheduled-stays", 1000);
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
