import { type Page, expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// Edit, answer again, the versions of a message and the card that waits for the person (ADR-0082 and ADR-0071, stage CU2) in a
// real browser. The engine is the mock of mock-api.ts; the saved conversation below is a tree with a second version of an
// answer, or with a parked card. `@layout` cases run in CI; the pictures (`@visual`) are kept per operating system.

const ID = "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80";
const RUN = "5b6c1c1e-0000-4000-8000-000000000009";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

const row = (id: string, seq: number, role: string, parent: string | null, parts: object[]) => ({
  id,
  seq,
  role,
  created_at: "2026-10-20T00:00:00Z",
  parent_id: parent,
  parts,
});
const text = (t: string) => [{ type: "text", text: t }];

async function saved(page: Page, messages: object[], head: string) {
  await page.route(`**/api/products/wasifyai-assistant/conversations/${ID}*`, (route) => {
    if (route.request().method() !== "GET") return route.fulfill({ status: 200, body: "{}" });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: ID,
        title: "A poem about a fox",
        created_at: "2026-10-20T00:00:00Z",
        updated_at: "2026-10-20T00:00:00Z",
        head_id: head,
        messages,
      }),
    });
  });
}

const TREE = [
  row("u1", 1, "user", null, text("Write a short poem about a fox.")),
  row("a1", 2, "assistant", "u1", text("A fox in the snow, quiet and bright.")),
  row("a1b", 3, "assistant", "u1", text("Red fur on white, a flicker of light.")),
];

async function noSideScroll(page: Page) {
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
}

test("an answer with two versions shows 2 / 2 and moves between them @layout", async ({ page }) => {
  const patched: unknown[] = [];
  await saved(page, TREE, "a1b");
  await page.route(`**/api/products/wasifyai-assistant/conversations/${ID}`, async (route, req) => {
    if (req.method() === "PATCH") {
      patched.push(JSON.parse(req.postData() ?? "{}"));
      return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    }
    return route.fallback();
  });
  await page.goto(`/chat/${ID}`);
  await expect(page.getByText("Red fur on white")).toBeVisible();
  await expect(page.getByRole("group", { name: "Versions of this message" })).toContainText(
    "2 / 2",
  );
  await page.getByRole("button", { name: "Previous version" }).click();
  await expect(page.getByText("A fox in the snow")).toBeVisible();
  await expect(page.getByText("Red fur on white")).toHaveCount(0);
  await expect.poll(() => patched.length).toBe(1);
  expect(patched[0]).toEqual({ head_id: "a1" });
  await noSideScroll(page);
});

test("editing a message opens a box in place and sends under the same parent @layout", async ({
  page,
}) => {
  const seen: { input: Record<string, unknown> }[] = [];
  await saved(page, TREE.slice(0, 2), "a1");
  await page.route("**/api/products/wasifyai-assistant/runs", (route) => {
    seen.push(JSON.parse(route.request().postData() ?? "{}"));
    const f = (seq: number, event: string, data: object) =>
      `id: ${seq}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: RUN, thread_id: "t", seq, ts: "", ...data })}\n\n`;
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        f(1, "token", { node: "agent", text: "Snow and a shadow, a fox goes by." }) +
        f(2, "done", { outputs: { status: "done", conversation_id: ID, title: "T" } }),
    });
  });
  await page.goto(`/chat/${ID}`);
  await page.getByRole("button", { name: "Edit message" }).click();
  const edit = page.getByRole("textbox", { name: "Edit your message" });
  await expect(edit).toHaveValue("Write a short poem about a fox.");
  await edit.fill("Write a haiku about a fox.");
  await noSideScroll(page);
  await edit.locator("xpath=ancestor::form").getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Snow and a shadow, a fox goes by.", { exact: true })).toBeVisible();
  expect(seen[0]?.input).toMatchObject({
    text: "Write a haiku about a fox.",
    parent_message_id: "",
  });
  await expect(page.getByRole("group", { name: "Versions of this message" }).first()).toContainText(
    "2 / 2",
  );
});

const CARD = [
  row("u1", 1, "user", null, text("Draw a fox.")),
  row("a1", 2, "assistant", "u1", [
    { type: "text", text: "Let me draw it." },
    {
      type: "tool_call",
      id: "t1",
      name: "propose_action",
      arguments: { action_id: "image.generate", params: { prompt: "a fox" } },
    },
  ]),
  row("t", 3, "tool", "a1", [
    {
      type: "interrupt",
      kind: "confirm_action",
      status: "pending",
      tool_call_id: "t1",
      approval_id: "ap1",
      run_id: RUN,
      title: "Make a picture",
      summary: "Make a picture",
      effect: "make",
      params: { prompt: "a fox in the snow", size: "square" },
    },
  ]),
];

test("a parked card is shown after a reload, answers the run and the turn goes on @layout", async ({
  page,
}) => {
  const resumed: unknown[] = [];
  await saved(page, CARD, "t");
  await page.route(`**/api/runs/${RUN}/resume`, (route) => {
    resumed.push(JSON.parse(route.request().postData() ?? "{}"));
    const f = (seq: number, event: string, data: object) =>
      `id: ${seq}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: RUN, thread_id: "t", seq, ts: "", ...data })}\n\n`;
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        f(5, "tool_result", {
          id: "t1",
          name: "propose_action",
          status: "error",
          output: { action_id: "image.generate", message: "No engine in this test." },
        }) +
        f(6, "token", { node: "agent", text: "I could not make it." }) +
        f(7, "done", { outputs: { status: "done", conversation_id: ID, title: "T" } }),
    });
  });
  await page.goto(`/chat/${ID}`);
  const card = page.getByRole("region", { name: "Make a picture" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("a fox in the snow");
  await noSideScroll(page);
  await card.getByRole("button", { name: "Make it" }).click();
  await expect(page.getByText("I could not make it.", { exact: true })).toBeVisible();
  expect(resumed).toEqual([{ value: { approved: true } }]);
  await expect(page.getByText("Let me draw it.", { exact: true })).toHaveCount(1); // the same message
});

test("the versions and the card look right @visual", async ({ page }) => {
  await saved(page, [...CARD.slice(0, 2), CARD[2] as object], "t");
  await page.goto(`/chat/${ID}`);
  await expect(page.getByRole("region", { name: "Make a picture" })).toBeVisible();
  await expect(page).toHaveScreenshot("card-waiting.png");
});
