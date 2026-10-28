import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { type Page, test } from "@playwright/test";
import { NOTEBOOK_ID, mockApi } from "./mock-api";

// Pictures of every screen for the UI audit (docs/ui-audit-2026-10-27.md). Not a test: it writes files, and only
// when asked. The web app runs against the mock of mock-api.ts, so every screen shows sample data.
//
//   UI_AUDIT=1 pnpm --filter web exec playwright test e2e/ui-audit.spec.ts --project=desktop-light
//   UI_AUDIT=1 pnpm --filter web exec playwright test e2e/ui-audit.spec.ts --project=phone-dark

const OUT = join(__dirname, "..", "..", "..", "docs", "ui-audit");

test.skip(!process.env.UI_AUDIT, "writes the audit pictures only when UI_AUDIT=1");

const SCREENS: [string, string][] = [
  ["home", "/"],
  ["creations", "/creations"],
  ["image-create", "/image"],
  ["image-edit", "/image/edit"],
  ["image-inpaint", "/image/inpaint"],
  ["image-reference", "/image/reference"],
  ["image-library", "/image/library"],
  ["image-3d", "/image/3d"],
  ["video-create", "/video"],
  ["video-animate", "/video/animate"],
  ["video-extend", "/video/extend"],
  ["video-builder", "/video/builder"],
  ["video-library", "/video/library"],
  ["voice-speak", "/voice/speak"],
  ["voice-transcribe", "/voice/transcribe"],
  ["voice-voices", "/voice/voices"],
  ["voice-convert", "/voice/convert"],
  ["voice-edit", "/voice/edit"],
  ["voice-dub", "/voice/dub"],
  ["voice-audiobook", "/voice/audiobook"],
  ["voice-lipsync", "/voice/lipsync"],
  ["music-create", "/voice/music"],
  ["music-tracks", "/voice/tracks"],
  ["music-lyrics", "/voice/lyrics"],
  ["music-separate", "/voice/separate"],
  ["notebooks", "/notebooks"],
  ["notebook", `/notebooks/${NOTEBOOK_ID}`],
  ["train", "/train"],
  ["explore", "/explore"],
  ["design", "/design"],
];

test.beforeEach(async ({ page }) => {
  mkdirSync(OUT, { recursive: true });
  await mockApi(page);
});

async function shot(page: Page, name: string) {
  const width = page.viewportSize()?.width ?? 1280;
  const dark = await page.evaluate(() => matchMedia("(prefers-color-scheme: dark)").matches);
  const suffix = width < 768 ? "-phone" : dark ? "-dark" : "";
  await page.waitForTimeout(600);
  await page.screenshot({ path: join(OUT, `${name}${suffix}.png`), fullPage: width >= 768 });
}

for (const [name, path] of SCREENS) {
  test(name, async ({ page }) => {
    await page.goto(path);
    await page.locator("#main").waitFor();
    await shot(page, name);
  });
}

test("side menu open with every group", async ({ page }) => {
  await page.goto("/image");
  const width = page.viewportSize()?.width ?? 1280;
  if (width < 768) {
    await page.getByRole("button", { name: /show or hide the side panel/i }).click();
  }
  const nav = page.getByRole("navigation", { name: "Main" });
  for (const group of ["Notebook", "Images", "Video", "Voice", "Music"]) {
    const button = nav.getByRole("button", { name: group, exact: true });
    if ((await button.getAttribute("aria-expanded")) !== "true") await button.click();
    await page.waitForTimeout(150);
  }
  await shot(page, "menu-open");
});

test("search open", async ({ page }) => {
  await page.goto("/image");
  await page.keyboard.press("Meta+K");
  await page.waitForTimeout(400);
  await shot(page, "search");
});
