import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { NOTEBOOK_ID, mockApi } from "./mock-api";

// Every screen against the accessibility rules of WCAG 2.2 A and AA (ADR-0093, stage U12; decision 4): names of
// controls, labels, contrast in the theme of the project (light, dark, phone), headings, landmarks and ARIA. A rule
// that fails names the screen, the rule and the elements, so the fix is in the screen and not in this list.

const SCREENS: [string, string][] = [
  ["home", "/"],
  ["saved chat", "/chat/0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80"],
  ["library", "/creations"],
  ["image create", "/image"],
  ["image edit", "/image/edit"],
  ["image inpaint", "/image/inpaint"],
  ["image reference", "/image/reference"],
  ["3d model", "/image/3d"],
  ["video create", "/video"],
  ["video animate", "/video/animate"],
  ["video extend", "/video/extend"],
  ["motion graphics", "/video/builder"],
  ["speech", "/voice/speak"],
  ["transcribe", "/voice/transcribe"],
  ["voices", "/voice/voices"],
  ["change a voice", "/voice/convert"],
  ["edit speech", "/voice/edit"],
  ["dub", "/voice/dub"],
  ["audiobook", "/voice/audiobook"],
  ["lip sync", "/voice/lipsync"],
  ["music", "/voice/music"],
  ["lyrics", "/voice/lyrics"],
  ["split", "/voice/separate"],
  ["notebooks", "/notebooks"],
  ["notebook", `/notebooks/${NOTEBOOK_ID}`],
  ["new notebook", "/notebooks/new"],
  ["train", "/train"],
  ["explore", "/explore"],
  ["design", "/design"],
];

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

for (const [name, path] of SCREENS) {
  test(`${name} meets the accessibility rules @layout @a11y`, async ({ page }) => {
    await page.goto(path);
    await page.locator("#main, main").first().waitFor();
    await page.waitForTimeout(800); // what the screen reads from the engine is on it
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    const found = result.violations.map(
      (v) =>
        `${v.id} (${v.impact}): ${v.help}\n${v.nodes
          .slice(0, 5)
          .map(
            (n) => `    ${n.target.join(" ")}  ${n.failureSummary?.split("\n")[1]?.trim() ?? ""}`,
          )
          .join("\n")}`,
    );
    expect(found, found.join("\n")).toEqual([]);
  });
}

test("high contrast keeps the focus ring and the chosen chip visible @layout @a11y", async ({
  page,
}) => {
  await page.emulateMedia({ forcedColors: "active" });
  await page.goto("/image");
  const chosen = page.locator('[aria-pressed="true"]').first();
  await expect(chosen).toBeVisible();
  // a filled background is dropped in forced colours: the chosen one is drawn with an outline instead
  expect(await chosen.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
  await page.keyboard.press("Tab");
  const focused = page.locator(":focus-visible");
  await expect(focused).toHaveCount(1);
  expect(await focused.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
});

test("less motion switches the moving parts off @layout @a11y", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/image");
  const chip = page.locator('[aria-pressed="true"]').first();
  await expect(chip).toBeVisible();
  const seconds = await chip.evaluate((el) =>
    Number.parseFloat(getComputedStyle(el).transitionDuration),
  );
  expect(seconds).toBeLessThan(0.01);
});

// A keyboard-only walk: Tab through each screen from the top. Every stop shows where the focus is and says what it
// is, and the walk reaches the screen's own content, not only the side menu and the bar.
for (const [name, path] of SCREENS) {
  test(`${name} can be walked with the keyboard @layout @a11y`, async ({ page }) => {
    await page.goto(path);
    await page.locator("#main, main").first().waitFor();
    await page.waitForTimeout(600);
    const problems: string[] = [];
    let inMain = false;
    for (let i = 0; i < 60; i++) {
      await page.keyboard.press("Tab");
      const stop = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        const style = getComputedStyle(el);
        const ring =
          (style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) > 0) ||
          style.boxShadow !== "none" ||
          el.matches("input, textarea, select, [contenteditable]"); // a field shows its caret and border
        const label =
          el.getAttribute("aria-label") ||
          el.getAttribute("aria-labelledby") ||
          el.getAttribute("title") ||
          (el as HTMLInputElement).labels?.[0]?.textContent ||
          el.textContent ||
          el.getAttribute("placeholder") ||
          "";
        const box = el.getBoundingClientRect();
        return {
          what: `${el.tagName.toLowerCase()} "${label.trim().slice(0, 40)}"`,
          ring,
          named: label.trim().length > 0,
          seen: box.width > 0 && box.height > 0,
          inMain: Boolean(el.closest("#main, main, [data-slot=make-screen]")),
        };
      });
      if (!stop) continue;
      if (stop.inMain) inMain = true;
      if (!stop.seen) problems.push(`${stop.what} is focused but not on the screen`);
      else if (!stop.ring) problems.push(`${stop.what} shows no focus`);
      if (!stop.named) problems.push(`${stop.what} has no name`);
    }
    expect(problems, problems.join("\n")).toEqual([]);
    expect(inMain, "the keyboard never reaches the screen's content").toBe(true);
  });
}
