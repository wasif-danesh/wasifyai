import { expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The release gate's browser half (ADR-0087, P8): the desktop's side menu, walked on the web. Every group is opened and
// every item it offers is visited; a page that is missing ("We couldn't find that"), an item that points nowhere, or a
// screen that fails to draw fails the run. `lib/parity.test.ts` holds the other half (a decision for every item).

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

const phone = (width: number | undefined) => (width ?? 1280) < 768;

test("every item of the side menu opens a page that draws @layout", async ({ page }) => {
  await page.goto("/image");
  const open = async () => {
    if (phone(page.viewportSize()?.width)) {
      await page.getByRole("button", { name: /show or hide the side panel/i }).click();
    }
    return page.getByRole("navigation", { name: "Main" });
  };
  const nav = await open();
  const hrefs = new Set<string>();
  // one group is open at a time: open each in turn and note what it offers
  for (const group of ["Notebook", "Images", "Video", "Voice", "Music"]) {
    const button = nav.getByRole("button", { name: group, exact: true });
    // retried: a click can land before the page is interactive
    await expect(async () => {
      if ((await button.getAttribute("aria-expanded")) !== "true") await button.click();
      await expect(button).toHaveAttribute("aria-expanded", "true", { timeout: 1000 });
    }).toPass({ timeout: 10_000 });
    for (const link of await nav.getByRole("link").all()) {
      const href = await link.getAttribute("href");
      if (href?.startsWith("/")) hrefs.add(href);
    }
  }
  // the groups of the desktop menu all contribute links, so the walk is not empty
  expect(hrefs.size).toBeGreaterThan(12);
  for (const href of hrefs) {
    const response = await page.goto(href);
    expect(response?.status(), `${href} answered with an error`).toBeLessThan(400);
    await expect(page.locator("#main"), `${href} drew nothing`).toBeVisible();
    await expect(
      page.getByText("We couldn't find that"),
      `${href} is a page that does not exist`,
    ).toHaveCount(0);
  }
});
