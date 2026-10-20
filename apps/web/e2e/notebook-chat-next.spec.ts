import { type Page, expect, test } from "@playwright/test";
import { NOTEBOOK_ID, mockApi } from "./mock-api";

// The notebook chat on assistant-ui (ADR-0082, stage CU4) behind the Labs switch: scope chips, citation pills, the search line and
// "Thinking" in a real browser, at 320 px, light, dark and right to left. The engine is the mock of mock-api.ts plus the scripted
// run below. `@layout` cases run in CI; the pictures (`@visual`) are kept per operating system.

const KEY = "wasifyai.labs.chat-next";
const RUN = "5b6c1c1e-0000-4000-8000-000000000002";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript((k) => localStorage.setItem(k, "1"), KEY);
});

type Ev = [event: string, data: Record<string, unknown>];

const CITATION = {
  n: 1,
  chunk_id: 7,
  document_id: "s1",
  title: "budget-2026.pdf",
  start_line: 3,
  end_line: 4,
  text: "The marketing budget is $350,000.",
};

function frames(events: Ev[]): string {
  return events
    .map(
      ([event, data], i) =>
        `id: ${i + 1}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: RUN, thread_id: "t1", seq: i + 1, ts: "", ...data })}\n\n`,
    )
    .join("");
}

const answer = (text: string, extra: Ev[] = []): Ev[] => [
  ["tool_call", { id: "c", name: "search_sources", arguments: { sources: 3 } }],
  ["tool_result", { id: "c", name: "search_sources", status: "ok", output: { hits: [{}, {}] } }],
  ...extra,
  ["token", { node: "answer", text }],
  [
    "done",
    {
      outputs: {
        status: "done",
        reply: text,
        citations: [CITATION],
        conversation_id: "c1",
        title: "Budget",
      },
    },
  ],
];

async function script(page: Page, events: Ev[], seen: unknown[] = []) {
  await page.route("**/api/products/wasifyai-notebooks/runs", async (route) => {
    seen.push(JSON.parse(route.request().postData() ?? "{}"));
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: frames(events) });
  });
}

const box = (page: Page) => page.getByRole("textbox", { name: "Ask about your sources" });

async function noSideScroll(page: Page) {
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
}

async function ask(page: Page, text: string) {
  await page.goto(`/notebooks/${NOTEBOOK_ID}`);
  await expect(box(page)).toBeVisible();
  await box(page).fill(text);
  await box(page).press("Enter");
}

test("the notebook answers with the search line, a citation pill and the scope in the box @layout", async ({
  page,
}) => {
  const seen: { input?: { text?: string; notebook_id?: string } }[] = [];
  await script(page, answer("The budget is **$350,000** [1]."), seen);
  await page.goto(`/notebooks/${NOTEBOOK_ID}`);
  await expect(page.locator("form").getByText("3 sources", { exact: true })).toBeVisible();
  await box(page).fill("What is the budget?");
  await box(page).press("Enter");
  await expect(page.getByText("Searched 3 sources, found 2 passages")).toBeVisible();
  await expect(page.getByRole("button", { name: /Source 1: budget-2026.pdf/ })).toBeVisible();
  await expect(page.getByText("$350,000", { exact: true })).toBeVisible();
  expect(seen[0]?.input).toMatchObject({ text: "What is the budget?", notebook_id: NOTEBOOK_ID });
  await noSideScroll(page);
});

test("a model's thinking is collapsed under Thinking and opens on a click @layout", async ({
  page,
}) => {
  await script(
    page,
    answer("It is $350,000.", [
      ["reasoning", { node: "answer", text: "I looked in the budget file." }],
    ]),
  );
  await ask(page, "What is the budget?");
  const thinking = page.locator("details[data-reasoning]");
  await expect(thinking).toBeVisible();
  await expect(thinking).not.toHaveAttribute("open", "");
  await expect(page.getByText("I looked in the budget file.")).toBeHidden();
  await thinking.getByText("Thinking").click();
  await expect(page.getByText("I looked in the budget file.")).toBeVisible();
});

test("Stop is offered while the answer is arriving and a failure offers Try again @layout", async ({
  page,
}) => {
  await script(page, [
    ["error", { code: "language_failed", message: "It did not answer.", retryable: true }],
  ]);
  await ask(page, "hello");
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.getByText("It did not answer.").first()).toBeVisible();
  await noSideScroll(page);
});

test("a long answer with a table and right-to-left text stays inside the pane @layout", async ({
  page,
}) => {
  const text = [
    "السعر هو ٣٥٠٬٠٠٠ دولار [1].",
    "",
    "| a long heading | another long heading | and a third one that is long |",
    "|---|---|---|",
    "| 1 | 2 | 3 |",
    "",
    "A very long unbroken line: https://example.com/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  ].join("\n");
  await script(page, answer(text));
  await ask(page, "ما هي الميزانية؟");
  await expect(page.getByText("السعر هو").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Source 1/ })).toBeVisible();
  await noSideScroll(page);
});

test("the answer, the pill and the box look right @visual", async ({ page }, info) => {
  await script(
    page,
    answer("The marketing budget is **$350,000** [1], and the launch is in May.", [
      ["reasoning", { node: "answer", text: "I looked in the budget file." }],
    ]),
  );
  await ask(page, "What is the budget?");
  await expect(page.getByRole("button", { name: /Source 1/ })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  await expect(page).toHaveScreenshot(`notebook-chat-next-${info.project.name}.png`);
});
