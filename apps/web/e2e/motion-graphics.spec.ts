import { expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The first screen of Motion graphics: a long title in "Your videos" must not push into the column next to it, the
// heading must stay inside its column, and nothing may make the page scroll sideways (the bug of 2026-10-24).

const LONG =
  "The best way to predict the future is to invent it, said Alan Kay in 1971 at Xerox PARC";
const NOW = "2026-10-24T10:00:00Z";
const json = (body: unknown) => ({ contentType: "application/json", body: JSON.stringify(body) });

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  const base = "**/api/products/wasifyai-video/builder";
  await page.route(`${base}/status`, (r) =>
    r.fulfill(
      json({ ready: true, place: "service", fit: { verdict: "fits", reason: "" }, busy: false }),
    ),
  );
  await page.route(`${base}/templates`, (r) =>
    r.fulfill(
      json({
        templates: [
          {
            id: "quote",
            title: "Quote",
            description: "",
            fields: [],
            transparent: false,
            formats: ["mp4"],
          },
        ],
        shapes: {},
        themes: {},
        fonts: {},
      }),
    ),
  );
  await page.route(`${base}/projects`, (r) =>
    r.request().method() === "GET"
      ? r.fulfill(
          json({
            items: [
              {
                id: "p1",
                title: LONG,
                template: "quote",
                slots: { seconds: 30 },
                created_at: NOW,
                updated_at: NOW,
                renders: [],
                formats: ["mp4"],
                preview_times: [],
                can_undo: false,
              },
            ],
          }),
        )
      : r.continue(),
  );
});

for (const scheme of ["light", "dark"] as const) {
  for (const width of [390, 1000]) {
    test(`the first screen holds together at ${width} px, ${scheme} @layout`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/video/builder");
      const heading = page.getByRole("heading", { name: "What should we make?" });
      await expect(heading).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      const wide = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);

      const section = page.getByRole("region", { name: "What to make" });
      const list = page.getByRole("navigation", { name: "Your video projects" });
      const [s, l, h] = await Promise.all([
        section.boundingBox(),
        list.boundingBox(),
        heading.boundingBox(),
      ]);
      if (!s || !l || !h) throw new Error("a part of the screen is missing");
      expect(h.x + h.width, "the heading leaves its column").toBeLessThanOrEqual(s.x + s.width + 1);
      if (width >= 768) {
        expect(l.x + l.width, "the list runs into the main column").toBeLessThanOrEqual(s.x + 1);
      } else {
        expect(l.y + l.height, "the list sits on the main column").toBeLessThanOrEqual(s.y + 1);
      }
      await expect(
        page.getByRole("button", { name: "Fill in the form", exact: true }),
      ).toBeVisible();
      if (process.env.SHOTS)
        await page.screenshot({ path: `${process.env.SHOTS}/mg-${width}-${scheme}.png` });
    });
  }
}
