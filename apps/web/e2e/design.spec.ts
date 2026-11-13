import { expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The design page (stage U1 of the UI plan): every shared component in every state, in both themes and on a
// phone. The layout check runs everywhere; the screenshot is kept per operating system.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("the design page shows every component without sideways scroll @layout", async ({ page }) => {
  await page.goto("/design");
  // the page's own heading, inside its content (the bar carries a title of its own)
  await expect(
    page.locator("#main").getByRole("heading", { name: "Design", level: 1 }),
  ).toBeVisible();
  for (const section of ["Words", "Field", "Select", "Stage", "RecentStrip"]) {
    await expect(page.getByRole("region", { name: section })).toBeVisible();
  }
  await expect(page.getByRole("region", { name: "Result" }).first()).toBeVisible();
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
});

test("the design page looks right @visual", async ({ page }) => {
  await page.goto("/design");
  await expect(
    page.locator("#main").getByRole("heading", { name: "Design", level: 1 }),
  ).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  await expect(page).toHaveScreenshot("design.png", { fullPage: true });
});
