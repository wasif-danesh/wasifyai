import { expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The release gate's browser half (ADR-0087, P8): the desktop's side menu, walked on the web. Every group is opened and
// every item it offers is visited; a page that is missing ("We couldn't find that"), an item that points nowhere, or a
// screen that fails to draw fails the run. `lib/parity.test.ts` holds the other half (a decision for every item).

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

const phone = (width: number | undefined) => (width ?? 1280) < 768;

test("every entry of the side menu and every tab it leads to opens a page that draws @layout", async ({
  page,
}) => {
  await page.goto("/image");
  const open = async () => {
    if (phone(page.viewportSize()?.width)) {
      await page.getByRole("button", { name: /show or hide the side panel/i }).click();
    }
    return page.getByRole("navigation", { name: "Main" });
  };
  const nav = await open();
  const hrefs = new Set<string>();
  // the menu has no groups since stage U2: every entry is a link (or a Soon button); a product's tools are the
  // tabs of the top bar on its page
  for (const link of await nav.getByRole("link").all()) {
    const href = await link.getAttribute("href");
    if (href?.startsWith("/")) hrefs.add(href);
  }
  expect(hrefs.size).toBeGreaterThan(8);
  for (const href of [...hrefs]) {
    await page.goto(href);
    for (const tab of await page
      .getByRole("navigation", { name: "Modes" })
      .getByRole("link")
      .all()) {
      const h = await tab.getAttribute("href");
      if (h?.startsWith("/")) hrefs.add(h);
    }
  }
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
