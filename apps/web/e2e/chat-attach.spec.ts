import { type Page, expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// Attaching files in the chat box (ADR-0083, stage CO2) in a real browser, on the new chat: the picker, the chips in the box, what the
// run is told and what the sent message shows. The engine is the mock of mock-api.ts plus the answers below.

const KEY = "wasifyai.labs.chat-next";
const RUN = "5b6c1c1e-0000-4000-8000-00000000000a";
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript((k) => localStorage.setItem(k, "1"), KEY);
  await page.route("**/api/products/wasifyai-assistant/options", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        thinking: false,
        attach: { available: true, images: true, documents: true, images_note: "" },
      }),
    }),
  );
  await page.route("**/api/products/wasifyai-assistant/uploads/images", (route) =>
    route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        upload_id: "p-1",
        key: "uploads/p-1.png",
        width: 1,
        height: 1,
        bytes: 70,
      }),
    }),
  );
  await page.route("**/api/products/wasifyai-assistant/attachments", (route) =>
    route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "d-1",
        kind: "document",
        name: "plan-for-the-launch-of-the-new-product.md",
        chars: 3200,
        pages: null,
        truncated: false,
      }),
    }),
  );
});

async function answer(page: Page, seen: unknown[]) {
  await page.route("**/api/products/wasifyai-assistant/runs", (route) => {
    seen.push(JSON.parse(route.request().postData() ?? "{}"));
    const f = (seq: number, event: string, data: object) =>
      `id: ${seq}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: RUN, thread_id: "t", seq, ts: "", ...data })}\n\n`;
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        f(1, "token", { node: "agent", text: "A single pixel, and a plan." }) +
        f(2, "done", {
          outputs: {
            status: "done",
            conversation_id: "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80",
            title: "T",
          },
        }),
    });
  });
}

async function noSideScroll(page: Page) {
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
}

async function attachBoth(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /^Attach/ })).toBeVisible();
  await page.getByLabel("Choose files to attach").setInputFiles([
    { name: "pixel.png", mimeType: "image/png", buffer: PNG },
    {
      name: "plan.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Plan\nLaunch on Friday."),
    },
  ]);
  await expect(page.getByAltText("pixel.png")).toBeVisible();
  await expect(page.getByText("3,200 characters")).toBeVisible();
}

test("a picture and a document are attached, sent with the words and shown on the message @layout", async ({
  page,
}) => {
  const seen: { input: Record<string, unknown> }[] = [];
  await answer(page, seen);
  await attachBoth(page);
  await noSideScroll(page);
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("What is in these?");
  await box.press("Enter");
  await expect(page.getByText("A single pixel, and a plan.", { exact: true })).toBeVisible();
  expect(seen[0]?.input).toMatchObject({
    text: "What is in these?",
    attachments: [
      { id: "p-1", name: "pixel.png" },
      { id: "d-1", name: "plan-for-the-launch-of-the-new-product.md" },
    ],
  });
  await expect(page.getByAltText("pixel.png")).toHaveCount(1); // on the message, and no longer in the box
  await expect(page.getByRole("button", { name: /^Remove/ })).toHaveCount(0);
  await noSideScroll(page);
});

test("the chips in the box look right @visual", async ({ page }) => {
  await attachBoth(page);
  await page.getByRole("textbox", { name: "Message" }).fill("What is in these?");
  await expect(page).toHaveScreenshot("attach-chips.png");
});
