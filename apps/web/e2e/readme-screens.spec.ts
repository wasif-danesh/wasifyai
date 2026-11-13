import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { type Page, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// The pictures in the README (docs/images/screens). Not a test: it writes files, and only when asked,
//
//   README_SHOTS=1 pnpm --filter web exec playwright test e2e/readme-screens.spec.ts --project=desktop-light
//
// The web app runs against the mock of mock-api.ts, so every screen shows sample data. Re-run it after a change to how
// the chat looks, and look at the pictures before committing them.

const OUT = join(__dirname, "..", "..", "..", "docs", "images", "screens");
const ID = "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80";
const RUN = "5b6c1c1e-0000-4000-8000-0000000000aa";
const SCENE = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAKAAAAB4CAIAAAD6wG44AAAEZklEQVR42u2dSU9TURiG71WccHblvDAOMS6MC+NCiEF0hxPOgCiKFnD8EwylDCJWJIZoVBAEQVCDsSBBMMY4xSkKiAsVcOUQZ43RjY2zlvbc9pxznzffBmjP7fne8/Z7uAnFfLEvzkD6KuyLYdIFnQ02MFjzBJsYTIIRMxjJmmDeokkwYgYjKBqRYMQMRlA0IsHMYARFIxKMmMEIilZZoxcO+f2bTz2vSbDaGrNwsC+u93jeMIOVsza8t+egx/MWilZDYxcM8u9MdDe8I8HyuzswkJPR3fCeGSyvxi0YEPj56Gr4AEVL6W50f1GnpKvxIwmWS+Oj+4k9K08aPzGD9ZYJRcuiCfP7WvCWEPb4/GcSTIiZwcpKoClQtP+aGGXZyvPNR00kWIakSR9iZrCkBovyBYqW9eyYJBiQZgYD0lC0tAEmwaHWw+YBk+Z9sGhl7mQxgKFo2yO0YRh9DMO0VcUUtwlcrfNCuHB3Oy+EC3yF9prBi4rvGYYRU3z/lGO6HW5E25iixe36QcuQyZGvBa4mNnFm+9F0m3i6eP/dH7+sS5khcPEpka8CX6SjZajwXdtlBv/irtdvYet3tAwL2N1hVmzc1hQtdu/trcOnRrz0+7kWsZAtEryk6PYfN7+k6LbYC7W3jvDL3RHW7d28X+rUO6ZLi27++wEnU2cKv+i0iOe+PKytdaTBXxcqRNTfnbs46pvTc5/946dB+BXVvFfm0ti7Zftu+PKwmrRZunZA5xnso7vec6BnE7gXbQlRk2DLK9Z9rVeNiHVf0zTBOt6LXu6+4sezYt1XT2ydbfAZHRC1Shu6U16g2ZZW7L0cyNOrts1hBstbAbrrPR9QNERNgoNfKwsvCWnKysJL2vTEvFXh1uOoriq8KHbB49vnQtEQtfSbuHm8SINtrN7TYsWyFTsimcGhL4vc9Z4bKBqiJsHW1ZqCZksbtKagWW2KvlF5QN3jubagKTgXOrYzyoCiIWoZX/j1qhJFX3rc7sZgXq5sVzQzOHgVZHe95wmKhqhJcOAVn+8JSbPi8z3K9arPF8NUq+Lzz4UwEPH559RqFxStOVErluCEvLMhb1lC3lmFOqbSDF6XVy9JLNbl1UPREDUU3ZtKzD0jVeMSc89A0cIqMfe0hOFIzD0NRUPUUPT/an1OnbTtW59TB0UHVBtyaiWPyIacWigaooai/1RJrholDE5y1UDRva4kV7VCIU5yVUPREDUU7a2N2VXK+bsxuwqK9qk2ZVcqmuFN2ZVQNERtb4pOdlYobXCyswKK/mslO8s1CHGysxyKhqjtR9Gbs8q08XdzVhkU/VNtySrVLMNbskqhaIjaHhTtyDyipcGOzCNQtOnIPKxxiB2Zh6FoiFpfik7JOKS9vykZh2xK0akZB22S4dSMg1A0RK0XRaell9jK4LT0ktB8RkdjfRPx0lhQtO4G8x/AdU8wBmueYN6iSTBiBiMoGpFgxAxGUDQiwcxgBEUjEoyYwQiKRiQYMYNtqq9CJQsjYse/HAAAAABJRU5ErkJggg==",
  "base64",
);

test.skip(!process.env.README_SHOTS, "writes the README pictures only when README_SHOTS=1");

test.beforeEach(async ({ page }) => {
  mkdirSync(OUT, { recursive: true });
  await mockApi(page);
  await page.route("https://files.test/scene.png", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: SCENE }),
  );
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
          consent_text: "Searching the web sends your question to DuckDuckGo.",
          needs_key: false,
        },
        attach: { available: true, images: true, documents: true, images_note: "" },
      },
    }),
  );
});

const row = (id: string, seq: number, role: string, parent: string | null, parts: object[]) => ({
  id,
  seq,
  role,
  created_at: "2026-10-20T00:00:00Z",
  parent_id: parent,
  parts,
});
const text = (t: string) => ({ type: "text", text: t });

async function saved(page: Page, messages: object[], head: string) {
  await page.route(`**/api/products/wasifyai-assistant/conversations/${ID}*`, (route) =>
    route.fulfill({
      json: {
        id: ID,
        title: "A poem about a fox",
        created_at: "2026-10-20T00:00:00Z",
        updated_at: "2026-10-20T00:00:00Z",
        head_id: head,
        messages,
      },
    }),
  );
}

// the mock engine is always "making a video": that chip is not part of what the pictures are about
async function shot(page: Page, name: string) {
  await page.addStyleTag({ content: 'a[href^="/creations?show=videos"] { visibility: hidden; }' });
  await page.screenshot({ path: join(OUT, name) });
}

test("home", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Attach/ }).waitFor();
  await shot(page, "home.png");
});

test("a chat with a picture, the web, and two versions of an answer", async ({ page }) => {
  await saved(
    page,
    [
      row("u1", 1, "user", null, [
        text("What fox lives in the Arctic, and what does it look like? Here is my sketch."),
        {
          type: "attachment",
          kind: "image",
          id: "p1",
          name: "sketch.png",
          url: "https://files.test/scene.png",
        },
        { type: "attachment", kind: "document", id: "d1", name: "field-notes.md" },
      ]),
      row("a1", 2, "assistant", "u1", [
        text(
          "The **Arctic fox** has a thick white winter coat that turns brown or grey in summer.",
        ),
      ]),
      row("a1b", 3, "assistant", "u1", [
        {
          type: "tool_call",
          id: "t1",
          name: "web_search",
          arguments: { query: "arctic fox appearance" },
        },
        {
          type: "tool_result",
          id: "t1",
          name: "web_search",
          status: "ok",
          output: {
            provider_title: "DuckDuckGo",
            results: [
              {
                title: "Arctic fox",
                url: "https://wiki.test/arctic-fox",
                site: "wiki.test",
                snippet: "A small fox native to the Arctic regions.",
              },
              {
                title: "How the arctic fox survives winter",
                url: "https://nature.test/fox",
                site: "nature.test",
                snippet: "Its fur is the warmest of any mammal.",
              },
            ],
          },
        },
      ]),
      row("a1c", 4, "assistant", "a1b", [
        text(
          "Going by the sources, the **Arctic fox** is small, with a dense white winter coat (brown or grey in summer) and short ears that save heat.",
        ),
      ]),
    ],
    "a1c",
  );
  await page.goto(`/chat/${ID}`);
  await page.getByAltText("sketch.png").waitFor();
  await page.getByText("Going by the sources").waitFor();
  await page.locator('[data-streamdown="strong"]').first().waitFor(); // the markdown renderer loads a moment later
  await shot(page, "chat.png");
});

test("a card that asks first", async ({ page }) => {
  await saved(
    page,
    [
      row("u1", 1, "user", null, [text("Look up red foxes, then draw one for me.")]),
      row("a1", 2, "assistant", "u1", [
        text("I found a few sources. Let me draw it."),
        {
          type: "tool_call",
          id: "t1",
          name: "propose_action",
          arguments: { action_id: "image.generate", params: { prompt: "a red fox in snow" } },
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
          params: { prompt: "a red fox in snow", size: "square" },
        },
      ]),
    ],
    "t",
  );
  await page.goto(`/chat/${ID}`);
  await page.getByRole("region", { name: "Make a picture" }).waitFor();
  await shot(page, "card.png");
});

test("files in the box", async ({ page }) => {
  await page.route("**/api/products/wasifyai-assistant/uploads/images", (route) =>
    route.fulfill({
      status: 201,
      json: { upload_id: "p-1", key: "uploads/p-1.png", width: 160, height: 120, bytes: 1183 },
    }),
  );
  await page.route("**/api/products/wasifyai-assistant/attachments", (route) =>
    route.fulfill({
      status: 201,
      json: {
        id: "d-1",
        kind: "document",
        name: "quarterly-plan.pdf",
        chars: 3200,
        pages: 12,
        truncated: false,
      },
    }),
  );
  await page.goto("/");
  await page.getByLabel("Choose files to attach").setInputFiles([
    { name: "sketch.png", mimeType: "image/png", buffer: SCENE },
    { name: "quarterly-plan.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") },
  ]);
  await page.getByAltText("sketch.png").waitFor();
  await page.getByText("12 pages").waitFor();
  await page
    .getByRole("textbox", { name: "Message" })
    .fill("Summarise the plan and tell me what the sketch shows.");
  await shot(page, "attach.png");
});

for (const [name, path, heading] of [
  ["images", "/image", /make a picture/i],
  ["video", "/video", /make a video/i],
  ["voice", "/voice/speak", /text to speech/i],
  ["music", "/voice/music", /create music/i],
  ["notebooks", "/notebooks", /notebooks/i],
] as const) {
  test(`the ${name} screen`, async ({ page }) => {
    await page.goto(path);
    await page.getByRole("heading", { name: heading }).first().waitFor();
    await shot(page, `${name}.png`);
  });
}

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, colorScheme: "dark", hasTouch: true });
  test("a chat", async ({ page }) => {
    await saved(
      page,
      [
        row("u1", 1, "user", null, [
          text("Write a short poem about a fox."),
          {
            type: "attachment",
            kind: "image",
            id: "p1",
            name: "sketch.png",
            url: "https://files.test/scene.png",
          },
        ]),
        row("a1", 2, "assistant", "u1", [
          text("A fox in the snow, quiet and bright,\nleaves small footprints into the night."),
        ]),
        row("a1b", 3, "assistant", "u1", [
          text(
            "Red fur on white, a flicker of light,\na shadow that drifts through the hush of night.",
          ),
        ]),
      ],
      "a1b",
    );
    await page.goto(`/chat/${ID}`);
    await page.getByText("Red fur on white").waitFor();
    await shot(page, "phone.png");
  });
});
