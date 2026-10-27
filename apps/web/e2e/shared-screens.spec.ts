import { type Page, expect, test } from "@playwright/test";
import { NOTEBOOK_ID, mockApi } from "./mock-api";

// The screens the web app shares with the desktop window (packages/ui): the side menu, image and video
// create/edit/animate and the two libraries. `@layout` checks run everywhere; the screenshots (`@visual`) are kept
// per operating system, so CI runs the layout checks only.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

const phone = (page: Page) => (page.viewportSize()?.width ?? 1280) < 768;

/** The side menu on a phone is a drawer behind the panel button; on a desktop it is always there. */
async function menu(page: Page) {
  if (phone(page)) await page.getByRole("button", { name: /show or hide the side panel/i }).click();
  return page.getByRole("navigation", { name: "Main" });
}

async function settle(page: Page) {
  // the dev server keeps a socket open, so the network never goes idle: wait for fonts and let the screen draw
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
}

async function noSideScroll(page: Page) {
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
}

const SCREENS = [
  { name: "notebooks", path: "/notebooks", ready: /notebooks/i },
  { name: "notebook", path: `/notebooks/${NOTEBOOK_ID}`, ready: /./ },
  { name: "voice-speak", path: "/voice/speak", ready: /text to speech/i },
  { name: "voice-transcribe", path: "/voice/transcribe", ready: /speech to text/i },
  { name: "voice-voices", path: "/voice/voices", ready: /^voices$/i },
  { name: "voice-convert", path: "/voice/convert", ready: /change a voice/i },
  { name: "voice-edit", path: "/voice/edit", ready: /edit speech/i },
  { name: "voice-dub", path: "/voice/dub", ready: /dub a recording/i },
  { name: "voice-audiobook", path: "/voice/audiobook", ready: /audiobook/i },
  { name: "voice-lipsync", path: "/voice/lipsync", ready: /lip sync/i },
  { name: "music-create", path: "/voice/music", ready: /create music/i },
  { name: "music-tracks", path: "/voice/tracks", ready: /your music/i },
  { name: "music-lyrics", path: "/voice/lyrics", ready: /lyrics/i },
  { name: "music-separate", path: "/voice/separate", ready: /split into parts/i },
  { name: "home", path: "/", ready: /good|hello/i },
  {
    name: "chat",
    path: "/chat/0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80",
    ready: /a poem about a fox/i,
  },
  { name: "image-create", path: "/image", ready: /create images/i },
  { name: "image-edit", path: "/image/edit", ready: /edit a picture/i },
  { name: "image-library", path: "/image/library", ready: /your images|library/i },
  { name: "video-create", path: "/video", ready: /make a video/i },
  { name: "video-animate", path: "/video/animate", ready: /animate a picture/i },
  { name: "video-library", path: "/video/library", ready: /your videos/i },
] as const;

for (const screen of SCREENS) {
  test(`${screen.name} fits the screen and has the menu @layout`, async ({ page }) => {
    await page.goto(screen.path);
    await expect(page.getByRole("heading", { name: screen.ready }).first()).toBeVisible();
    await settle(page);
    await noSideScroll(page);
    const nav = await menu(page);
    for (const entry of ["Chat", "Notebooks", "Images", "Video", "Speech", "Music", "Library"]) {
      await expect(nav.getByRole("link", { name: entry, exact: true })).toBeVisible();
    }
    await expect(nav.getByRole("link", { name: "Wasify AI, home" })).toBeVisible();
    // one bar of one height on every screen (ADR-0093 decision 1)
    const bar = page.locator('[data-slot="app-bar"]');
    await expect(bar).toBeVisible();
    expect((await bar.boundingBox())?.height).toBe(48);
  });

  test(`${screen.name} looks right @visual`, async ({ page }) => {
    await page.goto(screen.path);
    await expect(page.getByRole("heading", { name: screen.ready }).first()).toBeVisible();
    if (screen.name === "chat")
      await expect(page.getByText(/footprints into the night/)).toBeVisible();
    if (screen.name.endsWith("library")) {
      await expect(page.getByRole("list", { name: /images|videos/i })).toBeVisible();
    }
    await settle(page);
    await expect(page).toHaveScreenshot(`${screen.name}.png`, {
      fullPage: !screen.name.includes("create"),
    });
  });
}

test("the older speech pages lead to the shared ones, and the menu marks them @layout", async ({
  page,
}) => {
  await page.goto("/text-to-speech");
  await expect(page).toHaveURL(/\/voice\/speak$/);
  const nav = await menu(page);
  await expect(nav.getByRole("link", { name: /Text to speech/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.goto("/speech-to-text");
  await expect(page).toHaveURL(/\/voice\/transcribe$/);
  await page.goto("/music");
  await expect(page).toHaveURL(/\/voice\/music$/);
  await page.goto("/lip-sync");
  await expect(page).toHaveURL(/\/voice\/lipsync$/);
});

test("the menu offers the voice screens the service can run @layout", async ({ page }) => {
  await page.goto("/voice/music");
  const nav = await menu(page);
  await expect(async () => {
    await nav.getByRole("button", { name: "Music", exact: true }).click();
    await expect(nav.getByRole("link", { name: /Split into parts/ })).toHaveAttribute(
      "href",
      "/voice/separate",
      { timeout: 1000 },
    );
  }).toPass({ timeout: 10_000 });
  await expect(nav.getByRole("link", { name: /Create/ }).first()).toBeVisible();
});

test("the menu marks the page and opens the group that holds it @layout", async ({ page }) => {
  await page.goto("/video/library");
  const nav = await menu(page);
  await expect(nav.getByRole("link", { name: /Your videos/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(nav.getByRole("link", { name: /Animate an image/ })).toHaveAttribute(
    "href",
    "/video/animate",
  );
  // another group can be opened by hand while on a page (retried: the click can land before the page is interactive)
  await expect(async () => {
    await nav.getByRole("button", { name: "Images", exact: true }).click();
    await expect(nav.getByRole("link", { name: /Your images/ })).toHaveAttribute(
      "href",
      "/image/library",
      { timeout: 1000 },
    );
  }).toPass({ timeout: 10_000 });
});

test("a picture is made, and can be downloaded @layout", async ({ page }) => {
  await page.goto("/image");
  await page.getByRole("textbox").first().fill("A lighthouse on a cliff at sunrise");
  await page.getByRole("button", { name: "Generate" }).click();
  await expect(page.getByRole("link", { name: /download/i })).toHaveAttribute(
    "href",
    "/api/products/wasifyai-image/images/i1/download",
  );
  await settle(page);
  await noSideScroll(page);
});

test("a video is made, and can be downloaded @layout", async ({ page }) => {
  await page.goto("/video");
  await page.getByRole("textbox").first().fill("A red fox walks through fresh snow at dawn");
  await page.getByRole("button", { name: /make my video/i }).click();
  await expect(page.getByRole("link", { name: /download/i })).toHaveAttribute(
    "href",
    "/api/products/wasifyai-video/videos/v1/download",
  );
  await noSideScroll(page);
});

test("the image library opens a picture with its recipe and download @layout", async ({ page }) => {
  await page.goto("/image/library");
  await page.getByRole("button", { name: /open: a lighthouse/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("link", { name: /download/i })).toBeVisible();
  await expect(dialog.getByRole("button", { name: /make it again/i })).toBeVisible();
  await noSideScroll(page);
});

test("the video library shows done, being made and failed clips @layout", async ({ page }) => {
  await page.goto("/video/library");
  await expect(page.getByText("Being made")).toBeVisible();
  await page.getByRole("button", { name: /open: a paper boat/i }).click();
  await expect(page.getByText(/took too long/i)).toBeVisible();
});

test("the home page is the assistant; a first answer gives the chat its address @layout", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const box = page.getByRole("textbox");
  // The first Enter can arrive before the page can use it, so the question is sent again, but only while it is not
  // on the screen yet: a slow first answer must not turn into a second question and a second answer.
  await expect(async () => {
    if ((await page.getByText("What is a fox?", { exact: true }).count()) === 0) {
      await box.fill("What is a fox?");
      await box.press("Enter");
    }
    await expect(page.getByText(/small, quick wild dog/).first()).toBeVisible({ timeout: 3000 });
  }).toPass({ timeout: 30_000 });
  await expect(page).toHaveURL(/\/chat\/0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80$/);
  await noSideScroll(page);
});

test("recent chats are in the menu and open their chat @layout", async ({ page }) => {
  await page.goto("/");
  const nav = await menu(page);
  await expect(nav.getByRole("link", { name: /new chat/i })).toHaveAttribute("href", "/");
  const recent = nav.getByRole("button", { name: "Plan for the launch", exact: true });
  await expect(recent).toBeVisible();
  await recent.click();
  await expect(page).toHaveURL(/\/chat\/1a2b3c4d-5e6f-4a1b-8c9d-0e1f2a3b4c5d$/);
});

test("explore shows what can be made, without the side menu @layout", async ({ page }) => {
  await page.goto("/explore");
  await expect(page.getByRole("heading", { name: /bring your ideas to life/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Video/ }).first()).toBeVisible();
  await noSideScroll(page);
});

test("the notebook list opens a notebook, and the menu marks it @layout", async ({ page }) => {
  await page.goto("/notebooks");
  await expect(page.getByText("Thesis reading")).toBeVisible();
  const nav = await menu(page);
  await expect(nav.getByRole("link", { name: /View notebooks/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(nav.getByRole("link", { name: /Create/ })).toHaveAttribute("href", "/notebooks/new");
  await noSideScroll(page);
});

test("a notebook shows its sources and fits the screen @layout", async ({ page }) => {
  await page.goto(`/notebooks/${NOTEBOOK_ID}`);
  // on a phone the three panes are tabs, and the chat is the one that opens
  if (phone(page)) await page.getByRole("button", { name: "Sources", exact: true }).click();
  await expect(page.getByText("budget-2026.pdf").first()).toBeVisible();
  await expect(page.getByText("Idea: second supplier").first()).toBeVisible();
  await settle(page);
  await noSideScroll(page);
});

test("sources that could not be read fit the pane and say so in full @layout", async ({ page }) => {
  await mockApi(page, { unreadableSources: true });
  await page.goto(`/notebooks/${NOTEBOOK_ID}`);
  if (phone(page)) await page.getByRole("button", { name: "Sources", exact: true }).click();
  await expect(page.getByText("Could not be read", { exact: true }).first()).toBeVisible();
  await settle(page);
  // the list does not scroll sideways, and every "Could not be read" label is fully inside it
  const list = page.getByRole("list").filter({ hasText: "PESTLE Template" }).first();
  const box = await list.boundingBox();
  const overflow = await list.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(overflow, "the sources list scrolls sideways").toBeLessThanOrEqual(1);
  const labels = page.getByText("Could not be read", { exact: true });
  for (let i = 0; i < (await labels.count()); i += 1) {
    const b = await labels.nth(i).boundingBox();
    expect(b && box && b.x + b.width <= box.x + box.width + 1, `label ${i} is cut off`).toBe(true);
  }
  await noSideScroll(page);
});
