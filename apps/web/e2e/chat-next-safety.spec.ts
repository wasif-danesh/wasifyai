import { expect, test } from "@playwright/test";
import {
  ADVERSARIAL,
  REMOTE,
  TRACKER,
} from "../../../packages/ui/src/chat/thread/markdown/adversarial";
import { mockApi } from "./mock-api";

// The permanent safety test of the new chat's markdown (ADR-0082 decision 4, spike CU0 section 8), in a real browser, on the
// production build: one adversarial answer, then the rules. The Vitest twin (packages/ui/src/chat/thread/markdown-safety.test.tsx)
// covers the parts that need no layout. Re-run on every streamdown or mermaid update.

const RUN = "5b6c1c1e-0000-4000-8000-000000000001";

test("a model's answer cannot run, load or link anything it should not @layout", async ({
  page,
}) => {
  await mockApi(page);
  const frame = (seq: number, event: string, data: object) =>
    `id: ${seq}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: RUN, thread_id: "t", seq, ts: "", ...data })}\n\n`;
  await page.route("**/api/products/wasifyai-assistant/runs", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        frame(1, "token", { node: "a", text: ADVERSARIAL }) +
        frame(2, "done", {
          outputs: {
            status: "done",
            conversation_id: "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80",
            title: "t",
          },
        }),
    }),
  );

  // the tracker: nothing may be requested from these, and nothing may leave the app's own origin at all
  const hits: string[] = [];
  const elsewhere: string[] = [];
  const dialogs: string[] = [];
  const origin = new URL(page.context().pages()[0]?.url() || "http://127.0.0.1:3100").origin;
  page.on("request", (r) => {
    const u = r.url();
    if (u.startsWith(TRACKER) || u.startsWith(REMOTE)) hits.push(u);
    const o = new URL(u);
    if (!["data:", "blob:", "about:"].includes(o.protocol) && o.hostname !== "127.0.0.1")
      elsewhere.push(u);
  });
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  void origin;

  await page.goto("/");
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("show me");
  await box.press("Enter");

  const thread = page.locator("[data-markdown]").first();
  await expect(thread).toBeVisible();
  // code is highlighted, maths is set, both diagrams are drawn: all offline
  await expect(page.locator("[data-streamdown='code-block'] span span").first()).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.locator(".katex").first()).toBeVisible({ timeout: 15_000 });
  await expect(
    page.locator("[data-streamdown='mermaid'] svg, svg[id^='mermaid']").first(),
  ).toBeVisible({
    timeout: 20_000,
  });
  await page.waitForTimeout(1500); // give a late request or script its chance

  // 1. nothing ran
  const flags = await page.evaluate(() =>
    Object.keys(window).filter((k) => k.startsWith("__pwned")),
  );
  expect(flags, "a payload ran").toEqual([]);
  expect(dialogs).toEqual([]);

  // 2. nothing was fetched from the tracker or from the remote host, and nothing left the app
  expect(hits, "a picture or label was requested").toEqual([]);
  expect(elsewhere, "a request left the app").toEqual([]);

  // 3. raw HTML is text, not elements
  const msg = page.locator("[data-markdown]").first();
  for (const tag of ["script", "iframe", "b", "img", "object", "embed", "form"])
    await expect(msg.locator(tag), `<${tag}> made from the answer`).toHaveCount(0);
  await expect(msg).toContainText("<script>window.__pwned1 = 1</script>");
  await expect(msg).toContainText("<b>bold by html</b>");

  // 4. the only address anywhere in the answer (a link, or the href of a diagram's node) is the https link, opened safely
  const hrefs = await msg.evaluate((root) =>
    Array.from(root.querySelectorAll("*")).flatMap((e) =>
      ["href", "xlink:href"].flatMap((n) =>
        e.getAttribute(n) ? [e.getAttribute(n) as string] : [],
      ),
    ),
  );
  expect(hrefs).toEqual(["https://example.com/page"]);
  const link = msg.locator("a[href]");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  await expect(link).toHaveAttribute("target", "_blank");

  // 5. no diagram has an HTML label (strict level, htmlLabels off) and no diagram holds a picture
  expect(await page.locator("[data-markdown] foreignObject").count()).toBe(0);
  expect(await page.locator("[data-markdown] svg image, [data-markdown] svg img").count()).toBe(0);
});
