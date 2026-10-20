// @vitest-environment jsdom
// The cases of chat.test.tsx, run against the new thread (ADR-0082, stage CU1). Only the wiring differs: the same fake engine,
// the same box and buttons found by their names, the same words on the screen.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, ImageSummary, ImagesApi, OnEvent, ParsedEvent } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { ChatScreenNext } from "./ChatScreenNext";

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
  options: async () => ({ thinking: false }),
  searchStatus: async () => {
    throw new Error("unused");
  },
  updateSearch: async () => {
    throw new Error("unused");
  },
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

describe("ChatScreenNext", () => {
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
      <ChatScreenNext
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
    expect(inputs).toEqual([
      {
        text: "Hi\nagain",
        client_message_id: expect.any(String),
        client_reply_id: expect.any(String),
      },
    ]);
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
    render(<ChatScreenNext runs={runs} assistant={assistant} images={images} />);
    const box = screen.getByRole("textbox", { name: "Message" });
    await user.type(box, "one{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(1));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "two{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(2));
    expect(inputs[1]).toMatchObject({ text: "two", conversation_id: "c9" });
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
      <ChatScreenNext runs={runs} assistant={assistant} images={images} onOpenCreation={onOpen} />,
    );
    await user.type(screen.getByRole("textbox", { name: "Message" }), "draw a teapot{Enter}");
    const pic = await screen.findByRole("img", { name: "a red teapot" });
    expect(pic).toHaveAttribute("src", image.image_url);
    await user.click(screen.getByRole("button", { name: /open in the library/i }));
    expect(onOpen).toHaveBeenCalledWith("image", "img-1");
  });

  it("shows what the assistant found in the notebooks, with a way to open the notebook", async () => {
    const runs = runsThat([
      ev("tool_call", { id: "t1", name: "search_notebooks", arguments: { query: "budget" } }),
      ev("tool_result", {
        id: "t1",
        name: "search_notebooks",
        status: "ok",
        output: {
          results: [
            {
              notebook_id: "nb-1",
              notebook: "Launch",
              document_id: "d-1",
              title: "plan.md",
              snippet: "The launch budget is 40,000 dollars.",
            },
          ],
        },
      }),
      ev("token", { text: "It is 40,000 dollars." }),
      ev("done", { outputs: { status: "done", conversation_id: "c1", title: "Budget" } }),
    ]);
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(
      <ChatScreenNext runs={runs} assistant={assistant} images={images} onOpenCreation={onOpen} />,
    );
    await user.type(screen.getByRole("textbox", { name: "Message" }), "my budget?{Enter}");
    expect(await screen.findByText("From your notebooks")).toBeInTheDocument();
    expect(screen.getByText("plan.md")).toBeInTheDocument();
    expect(screen.getByText(/40,000 dollars\.$/, { selector: "span" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open notebook" }));
    expect(onOpen).toHaveBeenCalledWith("notebook", "nb-1");
  });

  it("says plainly when the notebooks could not be searched", async () => {
    const runs = runsThat([
      ev("tool_call", { id: "t1", name: "search_notebooks", arguments: { query: "x" } }),
      ev("tool_result", {
        id: "t1",
        name: "search_notebooks",
        status: "error",
        output: { message: "The search model is not on this computer yet." },
      }),
      ev("done", { outputs: { status: "done", conversation_id: "c1", title: "x" } }),
    ]);
    const user = userEvent.setup();
    render(<ChatScreenNext runs={runs} assistant={assistant} images={images} />);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "look{Enter}");
    expect(
      await screen.findByText("The search model is not on this computer yet."),
    ).toBeInTheDocument();
  });

  it("plays the music the assistant made, in the chat, with a way to open it", async () => {
    const runs = runsThat([
      ev("tool_call", { id: "t1", name: "make_music", arguments: { description: "upbeat pop" } }),
      ev("tool_result", {
        id: "t1",
        name: "make_music",
        status: "ok",
        output: { track_id: "tr1", title: "Summer pop", seconds: 30 },
      }),
      ev("token", { text: "Here is your song." }),
      ev("done", { outputs: { status: "done", conversation_id: "c1", title: "Song" } }),
    ]);
    const tracks = vi.fn(async () => ({ title: "Summer pop", audio_url: "http://x/a.wav" }));
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(
      <ChatScreenNext
        runs={runs}
        assistant={assistant}
        images={images}
        tracks={tracks}
        onOpenCreation={onOpen}
      />,
    );
    await user.type(screen.getByRole("textbox", { name: "Message" }), "make a song{Enter}");
    const player = await screen.findByLabelText("Summer pop");
    expect(player).toHaveAttribute("src", "http://x/a.wav");
    expect(tracks).toHaveBeenCalledWith("tr1");
    await user.click(screen.getByRole("button", { name: "Open in Your music" }));
    expect(onOpen).toHaveBeenCalledWith("track", "tr1");
  });

  it("says when the music could not be made", async () => {
    const runs = runsThat([
      ev("tool_call", { id: "t1", name: "make_music", arguments: { description: "x" } }),
      ev("tool_result", { id: "t1", name: "make_music", status: "error", output: {} }),
      ev("done", { outputs: { status: "done", conversation_id: "c1", title: "Song" } }),
    ]);
    const user = userEvent.setup();
    render(<ChatScreenNext runs={runs} assistant={assistant} images={images} />);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "make a song{Enter}");
    expect(await screen.findByText("The music could not be made.")).toBeInTheDocument();
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
      <ChatScreenNext
        runs={runs}
        assistant={assistant}
        images={images}
        onNeedModel={onNeedModel}
      />,
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
    render(<ChatScreenNext runs={runs} assistant={assistant} images={images} />);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello{Enter}");
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalledTimes(2));
  });

  it("does not send while blocked, and says why", async () => {
    const runs = runsThat([]);
    const user = userEvent.setup();
    render(
      <ChatScreenNext
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
      <ChatScreenNext
        runs={runsThat([])}
        assistant={assistant}
        images={images}
        conversationId="c5"
      />,
    );
    expect(await screen.findByText("Earlier question")).toBeInTheDocument();
    // the bold word is its own element; which element a renderer uses for it is not what matters here
    expect(await screen.findByText("answer")).toBeInTheDocument();
  });
});
