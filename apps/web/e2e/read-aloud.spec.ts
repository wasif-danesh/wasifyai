import { type Page, expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// Read aloud under a reply (ADR-0083, CU3), on the chat, in a real browser: the speaker button, the
// request it posts, a real sound played by the page's audio element, the status in words, Stop, and no sideways scroll at phone width.
// The engine's answer is scripted: a short real WAV. `@layout` cases run in CI.

const ID = "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d81";
const REPLY =
  "A fox in the snow, **quiet** and bright. Then it ran. [Read more](https://example.com/x)";

/** 0.4 s of a quiet tone, 24 kHz mono 16-bit, as base64 (what the engine returns). */
function tone(seconds = 0.4): string {
  const rate = 24000;
  const n = Math.floor(rate * seconds);
  const buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + n * 2, 4);
  buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24);
  buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) buf.writeInt16LE(Math.round(Math.sin(i / 12) * 3000), 44 + i * 2);
  return buf.toString("base64");
}

async function setup(page: Page) {
  await mockApi(page);
  await page.route("**/api/products/wasifyai-assistant/options", (route) =>
    route.fulfill({ json: { thinking: false } }),
  );
  await page.route(`**/api/products/wasifyai-assistant/conversations/${ID}*`, (route) =>
    route.fulfill({
      json: {
        id: ID,
        title: "A fox",
        created_at: "2026-10-20T00:00:00Z",
        updated_at: "2026-10-20T00:00:00Z",
        head_id: "a1",
        messages: [
          {
            id: "u1",
            seq: 1,
            role: "user",
            created_at: "2026-10-20T00:00:00Z",
            parent_id: null,
            parts: [{ type: "text", text: "Tell me about a fox." }],
          },
          {
            id: "a1",
            seq: 2,
            role: "assistant",
            created_at: "2026-10-20T00:00:00Z",
            parent_id: "u1",
            parts: [{ type: "text", text: REPLY }],
          },
        ],
      },
    }),
  );
}

async function noSideScroll(page: Page) {
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
}

const start = (page: Page) => page.getByRole("button", { name: "Read this reply aloud" });
const stop = (page: Page) => page.getByRole("button", { name: "Stop reading aloud" });

test.describe("the chat", () => {
  test("nothing plays by itself; a press reads the reply passage by passage and then stops @layout", async ({
    page,
  }) => {
    await setup(page);
    const posted: { text: string; part: number }[] = [];
    await page.route("**/api/products/wasifyai-voice/read-aloud", async (route) => {
      const body = JSON.parse(route.request().postData() ?? "{}");
      posted.push(body);
      await route.fulfill({
        json: {
          audio: tone(),
          part: body.part,
          parts: 2,
          truncated: false,
          seconds: 0.4,
          model: "hosted-speak",
          displaced: null,
        },
      });
    });
    await page.goto(`/chat/${ID}`);
    await expect(page.getByText("A fox in the snow")).toBeVisible();
    await expect(start(page)).toBeVisible();
    await page.waitForTimeout(500);
    expect(posted, "reading starts only when asked").toHaveLength(0);

    await start(page).click();
    await expect(stop(page).or(start(page))).toBeVisible();
    // two passages of 0.4 s each: it asks for the second while the first plays, then finishes by itself
    await expect.poll(() => posted.map((p) => p.part)).toEqual([0, 1]);
    expect(posted[0]?.text, "the reply is sent as the model wrote it").toContain("**quiet**");
    await expect(start(page)).toBeVisible({ timeout: 8000 });
    await expect(page.getByText(/Reading aloud/)).toBeHidden();
    await noSideScroll(page);
  });

  test("the status is in words, Stop ends it, and a refusal is a sentence @layout", async ({
    page,
  }) => {
    await setup(page);
    let mode: "slow" | "refuse" = "slow";
    await page.route("**/api/products/wasifyai-voice/read-aloud", async (route) => {
      if (mode === "refuse") {
        return route.fulfill({
          status: 409,
          json: {
            detail: { code: "model_missing", message: "The voice is not on this computer yet." },
          },
        });
      }
      await new Promise((r) => setTimeout(r, 1200));
      return route.fulfill({
        json: {
          audio: tone(30),
          part: 0,
          parts: 1,
          truncated: false,
          seconds: 30,
          model: "hosted-speak",
          displaced: null,
        },
      });
    });
    await page.goto(`/chat/${ID}`);
    await start(page).click();
    await expect(page.getByText("Getting ready to read…")).toBeVisible();
    await expect(stop(page)).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("Reading aloud", { exact: true })).toBeVisible();
    await noSideScroll(page);
    await stop(page).click();
    await expect(start(page)).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByText("Reading aloud", { exact: true })).toBeHidden();

    mode = "refuse";
    await start(page).click();
    const alert = page.getByRole("alert", { name: "Read aloud" });
    await expect(alert).toContainText("The voice is not on this computer yet.");
    await noSideScroll(page);
    await alert.getByRole("button", { name: "Close" }).click();
    await expect(alert).toBeHidden();
  });
});
