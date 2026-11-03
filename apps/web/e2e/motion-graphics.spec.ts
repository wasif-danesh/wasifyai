import { expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The first screen of Motion graphics (the scenes start, ADR-0096): a long title in "Your videos" must stay inside its
// list, the heading must stay inside its column, and nothing may make the page scroll sideways (the bug of 2026-10-24).

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
      const heading = page.getByRole("heading", { name: "What do you want to promote?" });
      await expect(heading).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      const wide = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);

      const section = page.getByRole("region", { name: "New project" });
      const list = page.getByRole("navigation", { name: "Your video projects" });
      const title = list.getByText(LONG);
      await expect(title).toBeVisible();
      const [s, l, h, t] = await Promise.all([
        section.boundingBox(),
        list.boundingBox(),
        heading.boundingBox(),
        title.boundingBox(),
      ]);
      if (!s || !l || !h || !t) throw new Error("a part of the screen is missing");
      expect(h.x + h.width, "the heading leaves its column").toBeLessThanOrEqual(s.x + s.width + 1);
      // the scenes start (ADR-0096): the projects are under the new project, at every width
      expect(l.y, "the list sits on the new project").toBeGreaterThanOrEqual(s.y + s.height - 1);
      expect(t.x + t.width, "the long title leaves its list").toBeLessThanOrEqual(
        l.x + l.width + 1,
      );
      await expect(
        page.getByRole("button", { name: "Make a first version", exact: true }),
      ).toBeVisible();
      if (process.env.SHOTS)
        await page.screenshot({ path: `${process.env.SHOTS}/mg-${width}-${scheme}.png` });
    });
  }
}
