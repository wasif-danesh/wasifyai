import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The Motion graphics editor on the web (ADR-0096 MX2): the shared screen through the BFF's addresses, in
// every project (light, dark, phone). The engine is mocked here; the engine's side is tested in
// products/wasifyai-video/tests and the real walk is `ui-audit.sh light motion-editor`.

const BASE = "**/api/products/wasifyai-video/builder";
const ID = "a".repeat(32);
const THEME = { from: "#0b1220", to: "#1c2b4a", ink: "#f5f7fb", accent: "#4f8cff" };
const seconds = {
  id: "seconds",
  kind: "seconds",
  label: "Length",
  required: false,
  max_chars: 0,
  min: 3,
  max: 90,
  default: 30,
  choices: [],
  hint: "",
};
const words = (id: string, label: string, kind: string) => ({
  ...seconds,
  id,
  label,
  kind,
  required: true,
  max_chars: 80,
  min: 0,
  max: 0,
  default: null,
});
const CATALOGUE = {
  templates: [
    {
      id: "title",
      title: "Animated title",
      description: "A title.",
      transparent: false,
      formats: ["mp4"],
      fields: [words("title", "Title", "text"), seconds],
    },
    {
      id: "quote",
      title: "Quote",
      description: "What someone said.",
      transparent: false,
      formats: ["mp4"],
      fields: [words("quote", "Quote", "longtext"), seconds],
    },
  ],
  shapes: {},
  themes: {
    midnight: THEME,
    sunrise: THEME,
    forest: THEME,
    paper: THEME,
    night: THEME,
    sage: THEME,
    pulse: THEME,
  },
  fonts: { sans: "Inter" },
};
const DOC = {
  name: "Northbean launch",
  shape: "portrait",
  font: "sans",
  seconds: 9,
  scenes: [
    {
      id: "aaaaaaaa",
      name: "Hook",
      kind: "title",
      caption: "",
      transition: "fade",
      fields: { title: "Mornings are hard.", seconds: 4, theme: "midnight" },
    },
    {
      id: "bbbbbbbb",
      name: "Proof",
      kind: "quote",
      caption: "",
      transition: "none",
      fields: { quote: "Smooth, not bitter.", seconds: 5, theme: "forest" },
    },
  ],
};
const PROJECT = {
  id: ID,
  title: DOC.name,
  template: "scenes",
  slots: DOC,
  created_at: "2026-10-31T10:00:00Z",
  updated_at: "2026-10-31T10:00:00Z",
  renders: [],
  formats: ["mp4"],
  preview_times: [3.9, 8.9],
  can_undo: false,
  document: DOC,
};

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  const json = (route: import("@playwright/test").Route, body: unknown) =>
    route.fulfill({ json: body });
  await page.route(`${BASE}/status`, (r) =>
    json(r, { ready: true, fit: { verdict: "fits", reason: "" }, busy: false, place: "service" }),
  );
  await page.route(`${BASE}/templates`, (r) => json(r, CATALOGUE));
  await page.route(`${BASE}/projects?**`, (r) => json(r, { items: [PROJECT] }));
  await page.route(`${BASE}/projects`, (r) => json(r, { items: [PROJECT] }));
  await page.route(`${BASE}/projects/${ID}`, (r) => json(r, PROJECT));
  await page.route(`${BASE}/projects/${ID}/live`, (r) =>
    json(r, {
      path: "/products/wasifyai-video/builder/live/token/index.html",
      expires_at: Date.now() / 1000 + 3600,
    }),
  );
  await page.route(`${BASE}/live/token/**`, (r) =>
    r.fulfill({
      contentType: "text/html",
      body: "<!doctype html><title>Preview</title><body></body>",
    }),
  );
  await page.goto("/video/builder");
  await page.getByRole("button", { name: /Northbean launch/ }).click();
  await page.locator("[data-slot=scene-editor]").waitFor();
});

test("the editor opens the player through the BFF and shows the scenes", async ({ page }) => {
  await expect(page.getByText("Scene 1 of 2")).toBeVisible();
  await expect(page.locator("hyperframes-player")).toHaveAttribute(
    "src",
    "/api/products/wasifyai-video/builder/live/token/index.html?v=0",
  );
  await page.getByRole("button", { name: /Scene 2, Proof/ }).click();
  await expect(page.getByLabel(/^Quote/)).toHaveValue("Smooth, not bitter.");
});

test("the editor fits the screen and has no accessibility violations", async ({ page }) => {
  const editor = page.locator("[data-slot=scene-editor]");
  const overflows = await editor.evaluate((el) => el.scrollWidth > el.clientWidth);
  expect(overflows).toBe(false);
  // every control is reachable: the words, the length and the scenes
  for (const control of [page.getByLabel(/^Title/), page.getByRole("button", { name: "Remove" })]) {
    await control.scrollIntoViewIfNeeded();
    await expect(control).toBeVisible();
  }
  const result = await new AxeBuilder({ page })
    .include("[data-slot=scene-editor]")
    .exclude("hyperframes-player")
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(result.violations.map((v) => v.id)).toEqual([]);
});
