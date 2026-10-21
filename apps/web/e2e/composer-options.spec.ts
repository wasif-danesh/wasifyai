import { type Page, expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The options of the chat box (ADR-0083, stage CO1): Thinking. The mock engine says the
// model can think; the answers are scripted. `@layout` cases run in CI; the pictures (`@visual`) are kept per operating system.

const RUN = "5b6c1c1e-0000-4000-8000-000000000001";

type Ev = [event: string, data: Record<string, unknown>];
const DONE: Ev = [
  "done",
  {
    outputs: {
      status: "done",
      conversation_id: "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80",
      title: "t",
    },
  },
];

async function setup(page: Page, canThink = true) {
  await mockApi(page);
  await page.route("**/api/products/wasifyai-assistant/options", (route) =>
    route.fulfill({ json: { thinking: canThink } }),
  );
}

async function answers(page: Page, events: Ev[], seen: { input?: Record<string, unknown> }[] = []) {
  await page.route("**/api/products/wasifyai-assistant/runs", async (route) => {
    seen.push(JSON.parse(route.request().postData() ?? "{}"));
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: events
        .map(
          ([event, data], i) =>
            `id: ${i + 1}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: RUN, thread_id: "t", seq: i + 1, ts: "", ...data })}\n\n`,
        )
        .join(""),
    });
  });
}

const box = (page: Page) => page.getByRole("textbox", { name: "Message" });
const thinkingButton = (page: Page) => page.getByRole("button", { name: /^Thinking\./ });

async function noSideScroll(page: Page) {
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
}

test.describe("the chat", () => {
  test("no Thinking button for a model that cannot think @layout", async ({ page }) => {
    await setup(page, false);
    await page.goto("/");
    await expect(box(page)).toBeVisible();
    await expect(page.getByRole("button", { name: /^Thinking/ })).toHaveCount(0);
  });

  test("Thinking is off until pressed, then the message asks for it and the reasoning is collapsed @layout", async ({
    page,
  }) => {
    await setup(page);
    const seen: { input?: Record<string, unknown> }[] = [];
    await answers(
      page,
      [
        ["reasoning", { node: "agent", text: "The person wants " }],
        ["reasoning", { node: "agent", text: "a greeting." }],
        ["token", { node: "agent", text: "Hello there." }],
        DONE,
      ],
      seen,
    );
    await page.goto("/");
    await expect(thinkingButton(page)).toBeVisible();
    await expect(thinkingButton(page)).toHaveAttribute("aria-pressed", "false");
    await thinkingButton(page).click();
    await expect(thinkingButton(page)).toHaveAttribute("aria-pressed", "true");
    await box(page).fill("hi");
    await box(page).press("Enter");
    await expect(page.getByText("Hello there.", { exact: true })).toBeVisible();
    expect(seen[0]?.input).toMatchObject({ text: "hi", thinking: true });

    const block = page.locator("details[data-reasoning]");
    await expect(block).toHaveCount(1);
    await expect(block).not.toHaveAttribute("open", "");
    await expect(page.getByText("The person wants a greeting.")).toBeHidden();
    await block.getByText("Thinking", { exact: true }).click();
    await expect(page.getByText("The person wants a greeting.")).toBeVisible();
    await noSideScroll(page);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`${scheme}, 320 px: the bar fits and nothing scrolls sideways @layout`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.setViewportSize({ width: 320, height: 640 });
      await setup(page);
      await answers(page, [["token", { node: "agent", text: "ok" }], DONE]);
      await page.goto("/");
      await expect(thinkingButton(page)).toBeVisible();
      await noSideScroll(page);
      const bar = await thinkingButton(page).boundingBox();
      expect(bar?.height ?? 0).toBeGreaterThanOrEqual(24);
      expect((bar?.x ?? 0) + (bar?.width ?? 0)).toBeLessThanOrEqual(320);
      await box(page).fill("hi");
      await box(page).press("Enter");
      await expect(page.getByText("ok", { exact: true })).toBeVisible();
      await noSideScroll(page);
    });
  }

  test("looks right with the options bar @visual", async ({ page }) => {
    await setup(page);
    await page.goto("/");
    await expect(thinkingButton(page)).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(300);
    await thinkingButton(page).click();
    await expect(page).toHaveScreenshot("options-next-on.png");
  });
});

test("the choice is remembered for the conversation, and a stored thought is shown collapsed @layout", async ({
  page,
}) => {
  await setup(page);
  await page.goto("/");
  await thinkingButton(page).click();
  await page.reload();
  // a new chat has no id yet: the choice is kept for the "new" chat
  await expect(thinkingButton(page)).toHaveAttribute("aria-pressed", "true");
});
