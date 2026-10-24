import { expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The chat box on the web has the desktop's four options: Attach, Search, Thinking and Mic (ADR-0083), when the service can
// do them. They come from the same `/options` answer and the same shared box.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/products/wasifyai-assistant/options", (route) =>
    route.fulfill({
      json: {
        thinking: true,
        search: {
          available: true,
          consented: false,
          ready: false,
          provider: "duckduckgo",
          provider_title: "DuckDuckGo",
          consent_text:
            "Searching the web sends your question to DuckDuckGo, from this service. The results are read by the assistant. You can turn this off with the Search button.",
          needs_key: false,
        },
        attach: { available: true, images: true, documents: true, images_note: "" },
      },
    }),
  );
});

test("the box has Attach, Search, Thinking and Mic @layout", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  for (const name of [/^Attach/, /^Search\./, /^Thinking\./, /^Mic/]) {
    await expect(page.getByRole("button", { name }).first(), String(name)).toBeVisible();
  }
});

test("Search asks the person before anything is sent, and names the service @layout", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Search\./ }).click();
  await expect(
    page.getByText(/sends your question to DuckDuckGo, from this service/),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Allow search", exact: true })).toBeVisible();
});
