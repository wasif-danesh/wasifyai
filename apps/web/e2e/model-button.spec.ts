import { expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The "Select ... model" button is at the top of every screen that makes something with a model, on the web too (ADR-0086
// amendment of 2026-10-24). On the screens an admin sets up for the whole service it only shows what the service uses.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

const SCREENS = [
  { name: "image create", path: "/image", button: /Select image model|FLUX\.2 klein 4B/ },
  { name: "video create", path: "/video", button: /Select video model|LTX-Video 2B/ },
  { name: "chat", path: "/", button: /Select chat model|Gemma4 E4B/ },
] as const;

for (const screen of SCREENS) {
  test(`${screen.name} has the model button, and it names the model in use @layout`, async ({
    page,
  }) => {
    await page.goto(screen.path);
    const button = page.getByRole("button", { name: screen.button }).first();
    await expect(button).toBeVisible();
    // at the top of the screen, above where the work is done
    const box = await button.boundingBox();
    expect(box?.y ?? 999, "the button is not at the top").toBeLessThan(200);
    await button.click();
    if (process.env.SHOTS)
      await page.screenshot({
        path: `${process.env.SHOTS}/mb-${screen.name.replace(" ", "-")}.png`,
      });
    // the panel lists the model the service uses, in use, with nothing to download
    await expect(page.getByText("In use", { exact: true })).toBeVisible();
    await expect(page.getByText("Set up on this service by an admin.")).toBeVisible();
  });
}

test("3D model has the model button at the top, and it says Pixal3D is ready @layout", async ({
  page,
}) => {
  await page.route("**/api/products/wasifyai-model3d/m3d/status", (r) =>
    r.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ready: true, fit: null, busy: false, details: [], place: "service" }),
    }),
  );
  await page.goto("/image/3d");
  const button = page.getByRole("button", { name: /Pixal3D|Select 3D model/ }).first();
  await expect(button).toBeVisible();
  expect((await button.boundingBox())?.y ?? 999).toBeLessThan(200);
  await button.click();
  await expect(page.getByText("In use", { exact: true })).toBeVisible();
});

test("a saved chat on a phone does not scroll sideways @layout", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/chat/0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80"); // title, model button and tools share the bar
  await expect(page.getByRole("button", { name: /Gemma4 E4B/ }).first()).toBeVisible();
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
});
