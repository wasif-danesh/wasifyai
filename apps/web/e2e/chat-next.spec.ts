import { type Page, expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The new chat (ADR-0082, stage CU1) is behind a Labs switch, remembered in the browser. These cases are the parity checklist of
// docs/chat-ui-migration-plan.md run against it in a real browser: the engine is the mock of mock-api.ts plus the scripted
// answers below. `@layout` cases run in CI; the pictures (`@visual`) are kept per operating system.

const KEY = "wasifyai.labs.chat-next";
const RUN = "5b6c1c1e-0000-4000-8000-000000000001";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript((k) => localStorage.setItem(k, "1"), KEY);
});

type Ev = [event: string, data: Record<string, unknown>];

function frames(events: Ev[], from = 1): string {
  return events
    .map(
      ([event, data], i) =>
        `id: ${from + i}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: RUN, thread_id: "t1", seq: from + i, ts: "", ...data })}\n\n`,
    )
    .join("");
}

const DONE: Ev = [
  "done",
  {
    outputs: {
      status: "done",
      conversation_id: "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80",
      title: "A poem about a fox",
    },
  },
];

/** Script what the assistant answers next (the last handler registered answers first). */
async function answers(
  page: Page,
  events: Ev[],
  opts: { hold?: Promise<void>; seen?: unknown[] } = {},
) {
  await page.route("**/api/products/wasifyai-assistant/runs", async (route) => {
    opts.seen?.push(JSON.parse(route.request().postData() ?? "{}"));
    if (opts.hold) await opts.hold;
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: frames(events) });
  });
}

const box = (page: Page) => page.getByRole("textbox", { name: "Message" });

async function ask(page: Page, text: string) {
  await page.goto("/");
  await expect(box(page)).toBeVisible();
  await box(page).fill(text);
  await box(page).press("Enter");
}

async function noSideScroll(page: Page) {
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
}

test("the new chat answers, and the box is the same element before and after the first message @layout", async ({
  page,
}) => {
  const seen: unknown[] = [];
  await answers(
    page,
    [["token", { node: "agent", text: "A fox is a **small** wild dog." }], DONE],
    { seen },
  );
  await page.goto("/");
  const before = await box(page).elementHandle();
  await box(page).fill("What is a fox?");
  await box(page).press("Enter");
  await expect(page.getByText("small", { exact: true })).toBeVisible();
  await expect(page.getByText("What is a fox?")).toBeVisible();
  expect(await before?.evaluate((el) => el.isConnected)).toBe(true);
  expect(seen[0]).toMatchObject({ input: { text: "What is a fox?" }, run_id: expect.any(String) });
  await expect(page).toHaveURL(/\/chat\/0f3c1a52/);
  await noSideScroll(page);
});

test("Shift+Enter is a new line and Enter sends @layout", async ({ page }) => {
  const seen: unknown[] = [];
  await answers(page, [["token", { node: "agent", text: "ok" }], DONE], { seen });
  await page.goto("/");
  await box(page).fill("one");
  await box(page).press("Shift+Enter");
  await box(page).pressSequentially("two");
  await expect(box(page)).toHaveValue("one\ntwo");
  await box(page).press("Enter");
  await expect(page.getByText("ok", { exact: true })).toBeVisible();
  expect(seen).toHaveLength(1);
  expect((seen[0] as { input: { text: string } }).input.text).toBe("one\ntwo");
});

test("a saved chat opens by its address @layout", async ({ page }) => {
  await page.goto("/chat/0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80");
  await expect(page.getByText("Write a short poem about a fox.")).toBeVisible();
  await expect(page.getByText(/footprints into the night/)).toBeVisible();
});

test("Stop ends the answer and tells the engine which run @layout", async ({ page }) => {
  let release: () => void = () => {};
  const hold = new Promise<void>((resolve) => {
    release = resolve;
  });
  const seen: { run_id?: string }[] = [];
  await answers(page, [["token", { node: "agent", text: "never shown" }], DONE], { hold, seen });
  const cancelled: string[] = [];
  await page.route("**/api/runs/*/cancel", (route) => {
    cancelled.push(new URL(route.request().url()).pathname);
    return route.fulfill({ status: 204 });
  });
  await ask(page, "a long one");
  await expect(page.getByText("Thinking…")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await page.getByRole("button", { name: /Stop/ }).click();
  await expect(page.getByRole("button", { name: /Stop/ })).toHaveCount(0);
  await expect(box(page)).toBeEnabled();
  expect(cancelled).toEqual([`/api/runs/${seen[0]?.run_id}/cancel`]);
  release();
});

test("Try again after a failure sends the message once more @layout", async ({ page }) => {
  const seen: unknown[] = [];
  await answers(
    page,
    [["error", { code: "language_failed", message: "It did not answer.", retryable: true }]],
    { seen },
  );
  await ask(page, "hello");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect.poll(() => seen.length).toBe(2);
});

test("a connection that ends early is picked up again from the last event, with no text lost @layout", async ({
  page,
}) => {
  // the run's first stream ends after two events (the connection was cut); the rest is asked for by the run's id
  await answers(
    page,
    [
      ["token", { node: "agent", text: "First half, " }],
      ["token", { node: "agent", text: "second half." }],
    ].slice(0, 1) as Ev[],
  );
  const asked: { url: string; last: string | undefined }[] = [];
  await page.route("**/api/runs/*/events", (route) => {
    asked.push({
      url: new URL(route.request().url()).pathname,
      last: route.request().headers()["last-event-id"],
    });
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: frames([["token", { node: "agent", text: "second half." }], DONE], 2),
    });
  });
  await ask(page, "tell me");
  await expect(page.getByText("First half, second half.", { exact: true })).toBeVisible();
  expect(asked).toHaveLength(1);
  expect(asked[0]?.last).toBe("1");
  expect(asked[0]?.url).toMatch(/^\/api\/runs\/[0-9a-f-]{36}\/events$/);
});

test("a picture is made: progress first, then the picture with a way to open it @layout", async ({
  page,
}) => {
  await answers(page, [
    ["token", { node: "agent", text: "Drawing it. " }],
    ["tool_call", { id: "t1", name: "generate_image", arguments: { prompt: "a lighthouse" } }],
    ["tool_result", { id: "t1", name: "generate_image", status: "ok", output: { image_id: "i1" } }],
    ["token", { node: "agent", text: "Here it is." }],
    DONE,
  ]);
  await ask(page, "draw a lighthouse");
  await expect(page.getByRole("img", { name: /lighthouse/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open in the library" })).toBeVisible();
  await expect(page.getByText("Here it is.", { exact: true })).toBeVisible();
  await noSideScroll(page);
});

test("results of a search are a card in the answer @layout", async ({ page }) => {
  await answers(page, [
    ["tool_call", { id: "t1", name: "search_creations", arguments: { query: "lighthouse" } }],
    [
      "tool_result",
      {
        id: "t1",
        name: "search_creations",
        status: "ok",
        output: { results: [{ kind: "image", id: "i1", text: "A lighthouse at sunrise" }] },
      },
    ],
    ["token", { node: "agent", text: "Found one." }],
    DONE,
  ]);
  await ask(page, "find my lighthouse");
  await expect(page.getByText("Found 1 in your library")).toBeVisible();
  await expect(page.getByText("A lighthouse at sunrise")).toBeVisible();
});

test("a reply can be copied @layout", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await answers(page, [["token", { node: "agent", text: "Copy **this** please." }], DONE]);
  await ask(page, "say something");
  await page.getByRole("button", { name: "Copy reply" }).click();
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe("Copy **this** please.");
});

test("what a model writes is not markup, and only http(s) links open @layout", async ({ page }) => {
  await answers(page, [
    [
      "token",
      {
        node: "agent",
        text: "<script>window.__x=1</script>\n\n[ok](https://example.com) [bad](javascript:alert(1))",
      },
    ],
    DONE,
  ]);
  await ask(page, "x");
  await expect(page.getByRole("link", { name: "ok" })).toHaveAttribute(
    "href",
    "https://example.com/",
  );
  await expect(page.getByRole("link", { name: "bad" })).toHaveCount(0);
  await expect(page.getByText("<script>window.__x=1</script>")).toBeVisible();
});

test("the screen reader hears that the assistant is answering and then the answer, once @layout", async ({
  page,
}) => {
  await answers(page, [["token", { node: "agent", text: "A fox is a small wild dog." }], DONE]);
  await ask(page, "what is a fox");
  await expect(page.getByRole("log")).toHaveText("The assistant said: A fox is a small wild dog.");
  await expect(page.getByRole("status").filter({ hasText: "Answer ready." })).toHaveCount(1);
});

// ---- phone width, light and dark, right to left -------------------------------------------------------------------------

const LONG = [
  "Here is **bold** and a list:",
  "",
  "- one",
  "- two",
  "",
  "```ts",
  "const aVeryLongLineOfCode: number = 1234567890 + 1234567890 + 1234567890 + 1234567890;",
  "```",
  "",
  "| a long heading | another long heading | and a third one that is long |",
  "|---|---|---|",
  "| 1 | 2 | 3 |",
  "",
  "Supercalifragilisticexpialidocious-and-a-very-long-word-without-any-break-opportunity-at-all-in-it.",
].join("\n");

for (const scheme of ["light", "dark"] as const) {
  test(`at 320 px, ${scheme}: nothing scrolls sideways and the box is reachable @layout`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.setViewportSize({ width: 320, height: 640 });
    await answers(page, [["token", { node: "agent", text: LONG }], DONE]);
    await ask(page, "show me a long one");
    await expect(page.getByText("Here is", { exact: false }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy reply" })).toBeVisible();
    await expect(box(page)).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(300);
    await noSideScroll(page);
    const overflow = await page.evaluate(() => {
      const viewport = window.innerWidth;
      return Array.from(document.querySelectorAll("main *, [data-workspace] *"))
        .filter(
          (e) =>
            e.getBoundingClientRect().right > viewport + 1 &&
            !e.closest("pre, table, [data-streamdown='table-wrapper']"),
        )
        .slice(0, 5)
        .map((e) => `${e.tagName}.${String(e.className).slice(0, 60)}`);
    });
    expect(overflow, "elements wider than the screen").toEqual([]);
  });
}

test("right-to-left text is laid out right to left, in the bubble and in the answer @layout", async ({
  page,
}) => {
  await answers(page, [["token", { node: "agent", text: "مرحبا بك في هذا العالم الجميل" }], DONE]);
  await ask(page, "مرحبا");
  const bubble = page.getByText("مرحبا", { exact: true });
  await expect(bubble).toHaveCSS("direction", "rtl");
  const answer = page.getByText("مرحبا بك في هذا العالم الجميل", { exact: true }).first();
  await expect(answer).toHaveCSS("direction", "rtl");
  await noSideScroll(page);
});

test("the usual chat is still the default, and ?chat=next turns the new one on @layout", async ({
  page,
}) => {
  await page.addInitScript((k) => localStorage.removeItem(k), KEY);
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  // the new chat's box has a log region for the screen reader, the usual one has a live thread instead
  await expect(page.getByRole("log")).toHaveCount(0);
  await page.goto("/?chat=next");
  await expect(page.getByRole("log")).toHaveCount(1);
  await page.goto("/?chat=classic");
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  await expect(page.getByRole("log")).toHaveCount(0);
});

test("the new chat looks right, empty and answered @visual", async ({ page }) => {
  await answers(page, [
    [
      "token",
      {
        node: "agent",
        text: "Here is **bold** text and a list:\n\n- one\n- two\n\n```ts\nconst x: number = 1;\n```\n\n$$E = mc^2$$\n\nA [link](https://example.com).",
      },
    ],
    ["tool_call", { id: "t1", name: "generate_image", arguments: { prompt: "a lighthouse" } }],
    ["tool_result", { id: "t1", name: "generate_image", status: "ok", output: { image_id: "i1" } }],
    DONE,
  ]);
  await page.goto("/");
  await expect(box(page)).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  await expect(page).toHaveScreenshot("chat-next-empty.png");
  await box(page).fill("show me");
  await box(page).press("Enter");
  await expect(page.locator(".katex").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("img", { name: /lighthouse/i })).toBeVisible();
  await expect(page.locator("[data-streamdown='code-block'] span span").first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  await expect(page).toHaveScreenshot("chat-next-answer.png");
});
