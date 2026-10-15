// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, ImageSummary, ImagesApi, OnEvent, ParsedEvent } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { ChatScreen } from "./ChatScreen";
import { Markdown, inline, parseBlocks } from "./markdown";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

function runsThat(events: ParsedEvent[], inputs: object[] = []) {
  return {
    startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
      inputs.push(input);
      for (const e of events) on(e);
    }),
    watchRun: vi.fn(async () => {}),
  };
}

const assistant: AssistantApi = {
  list: async () => [],
  get: async (id) => ({
    id,
    title: "Saved chat",
    created_at: "",
    updated_at: "",
    messages: [
      {
        id: "m1",
        seq: 1,
        role: "user",
        created_at: "",
        parts: [{ type: "text", text: "Earlier question" }],
      },
      {
        id: "m2",
        seq: 2,
        role: "assistant",
        created_at: "",
        parts: [{ type: "text", text: "Earlier **answer**" }],
      },
    ],
  }),
  rename: async () => {
    throw new Error("unused");
  },
  remove: async () => {},
};

const image: ImageSummary = {
  id: "img-1",
  prompt: "a red teapot",
  mode: "text",
  width: 256,
  height: 256,
  created_at: "2026-10-16T00:00:00Z",
  image_url: "http://127.0.0.1:1/files/img-1.png",
  thumb_url: "http://127.0.0.1:1/files/img-1.jpg",
  recipe: null,
  favourite: false,
};

const images = {
  get: async () => image,
} as unknown as ImagesApi;

describe("markdown", () => {
  it("makes blocks of headings, lists, code and paragraphs", () => {
    const blocks = parseBlocks(
      "# Title\n\nSome *text*.\n\n- one\n- two\n\n1. a\n2. b\n\n```js\nlet x = 1;\n```",
    );
    expect(blocks.map((b) => b.kind)).toEqual(["heading", "p", "ul", "ol", "code"]);
    expect(blocks[4]).toEqual({ kind: "code", lang: "js", text: "let x = 1;" });
  });

  it("runs an unclosed code block to the end, as a half-streamed answer is", () => {
    const blocks = parseBlocks("Here:\n```py\nprint(1)");
    expect(blocks[1]).toEqual({ kind: "code", lang: "py", text: "print(1)" });
  });

  it("never makes markup of what a model writes, and only links http(s)", () => {
    const { container } = render(
      <Markdown
        text={"<script>alert(1)</script> [ok](https://example.com) [bad](javascript:alert(1))"}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    const links = [...container.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com"]);
    expect(links[0]?.getAttribute("rel")).toContain("noopener");
    expect(container.textContent).toContain("[bad](javascript:alert(1))");
  });

  it("renders bold, italic and inline code", () => {
    const { container } = render(<p>{inline("**b** and *i* and `c`")}</p>);
    expect(container.querySelector("strong")?.textContent).toBe("b");
    expect(container.querySelector("em")?.textContent).toBe("i");
    expect(container.querySelector("code")?.textContent).toBe("c");
  });
});

describe("ChatScreen", () => {
  it("sends on Enter, shows the answer as it arrives, and keeps Shift+Enter for a new line", async () => {
    const inputs: object[] = [];
    const runs = runsThat(
      [
        ev("token", { text: "Hello " }),
        ev("token", { text: "**there**" }),
        ev("done", { outputs: { status: "done", conversation_id: "c1", title: "Hi" } }),
      ],
      inputs,
    );
    const onConversation = vi.fn();
    const user = userEvent.setup();
    render(
      <ChatScreen
        runs={runs}
        assistant={assistant}
        images={images}
        onConversation={onConversation}
      />,
    );
    const box = screen.getByRole("textbox", { name: "Message" });
    await user.type(box, "Hi{Shift>}{Enter}{/Shift}again");
    expect(box).toHaveValue("Hi\nagain");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("there")).toBeInTheDocument();
    expect(screen.getByText(/Hi\s*again/)).toBeInTheDocument();
    expect(inputs).toEqual([{ text: "Hi\nagain" }]);
    await waitFor(() => expect(onConversation).toHaveBeenCalledWith("c1", "Hi"));
    expect(box).toHaveValue("");
  });

  it("continues the same conversation on the next message", async () => {
    const inputs: object[] = [];
    const runs = runsThat(
      [
        ev("token", { text: "ok" }),
        ev("done", { outputs: { status: "done", conversation_id: "c9", title: "T" } }),
      ],
      inputs,
    );
    const user = userEvent.setup();
    render(<ChatScreen runs={runs} assistant={assistant} images={images} />);
    const box = screen.getByRole("textbox", { name: "Message" });
    await user.type(box, "one{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(1));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "two{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(2));
    expect(inputs[1]).toEqual({ text: "two", conversation_id: "c9" });
  });

  it("shows a picture the assistant made, with a way to open it", async () => {
    const runs = runsThat([
      ev("token", { text: "Drawing. " }),
      ev("tool_call", { id: "t1", name: "generate_image", arguments: { prompt: "a red teapot" } }),
      ev("tool_result", {
        id: "t1",
        name: "generate_image",
        status: "ok",
        output: { image_id: "img-1" },
      }),
      ev("done", { outputs: { status: "done", conversation_id: "c1", title: "Teapot" } }),
    ]);
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(
      <ChatScreen runs={runs} assistant={assistant} images={images} onOpenCreation={onOpen} />,
    );
    await user.type(screen.getByRole("textbox", { name: "Message" }), "draw a teapot{Enter}");
    const pic = await screen.findByRole("img", { name: "a red teapot" });
    expect(pic).toHaveAttribute("src", image.image_url);
    await user.click(screen.getByRole("button", { name: /open in the library/i }));
    expect(onOpen).toHaveBeenCalledWith("image", "img-1");
  });

  it("says what is missing when no model is chosen, and offers the way there", async () => {
    const runs = runsThat([
      ev("error", {
        code: "no_language_model",
        message: "No language model is chosen yet.",
        retryable: false,
      }),
    ]);
    const onNeedModel = vi.fn();
    const user = userEvent.setup();
    render(
      <ChatScreen runs={runs} assistant={assistant} images={images} onNeedModel={onNeedModel} />,
    );
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello{Enter}");
    expect(await screen.findByText("No language model is chosen yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Choose a model" }));
    expect(onNeedModel).toHaveBeenCalled();
  });

  it("offers Try again for an error that may pass", async () => {
    const runs = runsThat([
      ev("error", { code: "language_failed", message: "It did not answer.", retryable: true }),
    ]);
    const user = userEvent.setup();
    render(<ChatScreen runs={runs} assistant={assistant} images={images} />);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello{Enter}");
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalledTimes(2));
  });

  it("does not send while blocked, and says why", async () => {
    const runs = runsThat([]);
    const user = userEvent.setup();
    render(
      <ChatScreen
        runs={runs}
        assistant={assistant}
        images={images}
        blockedReason="Choose a model first."
      />,
    );
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello{Enter}");
    expect(screen.getByText("Choose a model first.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(runs.startRun).not.toHaveBeenCalled();
  });

  it("opens a saved conversation", async () => {
    render(
      <ChatScreen runs={runsThat([])} assistant={assistant} images={images} conversationId="c5" />,
    );
    expect(await screen.findByText("Earlier question")).toBeInTheDocument();
    expect(screen.getByText("answer").tagName).toBe("STRONG");
  });
});
