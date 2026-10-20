// @vitest-environment jsdom
// What the new thread does beyond what the old screen did (ADR-0082, stage CU1): stop reaches the engine, a lost connection is
// picked up again instead of sent again, the screen reader is told, and the small things of the parity checklist.
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, ImagesApi, OnEvent, ParsedEvent } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { ChatScreenNext } from "../ChatScreenNext";
import { Announcer, plainText } from "./announcer";
import { toLikeMessage } from "./convert";
import { useThreadChat } from "./use-thread-chat";

const ev = (event: string, seq: number, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq, ...data } }) as unknown as ParsedEvent;

const assistant: AssistantApi = {
  options: async () => ({ thinking: false }),
  searchStatus: async () => {
    throw new Error("unused");
  },
  updateSearch: async () => {
    throw new Error("unused");
  },
  setHead: async () => {},
  attach: async () => {
    throw new Error("unused");
  },
  unattach: async () => {},
  list: async () => [],
  get: async () => {
    throw new Error("unused");
  },
  rename: async () => {
    throw new Error("unused");
  },
  remove: async () => {},
};
const images = { get: async () => ({}) } as unknown as ImagesApi;
const DONE = ev("done", 9, { outputs: { status: "done", conversation_id: "c1", title: "T" } });

function runsThat(script: (on: OnEvent, signal: AbortSignal) => Promise<void>) {
  const startRun = vi.fn(
    async (_p: string, _i: object, signal: AbortSignal, on: OnEvent, _id?: string) =>
      script(on, signal),
  );
  const watchRun = vi.fn(async (_r: string, _s: number, _g: AbortSignal, on: OnEvent) => {
    on(ev("token", 3, { text: "rest" }));
    on(DONE);
  });
  const cancelRun = vi.fn(async (_id: string) => {});
  return { startRun, watchRun, cancelRun };
}

describe("useThreadChat", () => {
  it("starts the run under an id chosen here and tells the engine which two ids it may store the messages under", async () => {
    const runs = runsThat(async (on) => {
      on(ev("token", 1, { text: "Hi" }));
      on(DONE);
    });
    const { result } = renderHook(() => useThreadChat({ runs, api: assistant }));
    await act(async () => result.current.send("hello"));
    const [, input, , , runId] = runs.startRun.mock.calls[0] ?? [];
    expect(runId).toMatch(/^[0-9a-f-]{36}$/);
    expect(input).toMatchObject({
      text: "hello",
      client_message_id: expect.any(String),
      client_reply_id: expect.any(String),
    });
    expect(result.current.state.chat.messages.map((m) => m.id)).toEqual([
      (input as Record<string, string>).client_message_id,
      (input as Record<string, string>).client_reply_id,
    ]);
  });

  it("Stop stops the run at the engine, by the run's id, and keeps what was said", async () => {
    let release: () => void = () => {};
    const runs = runsThat(
      (on, signal) =>
        new Promise<void>((resolve) => {
          on(ev("token", 1, { text: "Partial" }));
          release = resolve;
          signal.addEventListener("abort", () => resolve());
        }),
    );
    const { result } = renderHook(() => useThreadChat({ runs, api: assistant }));
    let sending: Promise<void> = Promise.resolve();
    act(() => {
      sending = result.current.send("long one");
    });
    await waitFor(() => expect(result.current.state.chat.phase).toBe("working"));
    act(() => result.current.stop());
    await act(async () => sending);
    release();
    // the id the engine reported for the run (the fake engine here names it "r1")
    expect(runs.cancelRun).toHaveBeenCalledWith("r1");
    expect(result.current.state.chat.phase).toBe("idle");
    expect(result.current.state.chat.messages[1]?.parts).toEqual([
      { type: "text", text: "Partial" },
    ]);
    expect(result.current.state.chat.messages[1]?.streaming).toBe(false);
  });

  it("picks a lost connection up again where it was; Try again does not send the message a second time", async () => {
    const runs = runsThat(async (on) => {
      on(ev("token", 1, { text: "Hel" }));
      on(ev("token", 2, { text: "lo " }));
    });
    // the network stays away for the first tries, then comes back
    let down = 4;
    runs.watchRun.mockImplementation(async (_r, _s, _g, on) => {
      if (down-- > 0) throw new TypeError("offline");
      on(ev("token", 3, { text: "there" }));
      on(DONE);
    });
    const { result } = renderHook(() =>
      useThreadChat({ runs, api: assistant, reconnect: { attempts: 3, delay: () => 1 } }),
    );
    await act(async () => result.current.send("hi"));
    expect(result.current.state.chat.error).toMatchObject({
      code: "connection_lost",
      retryable: true,
    });
    expect(result.current.state.chat.messages[1]?.parts).toEqual([
      { type: "text", text: "Hello " },
    ]);

    await act(async () => result.current.retry());
    await waitFor(() => expect(result.current.state.chat.phase).toBe("idle"));
    expect(runs.startRun).toHaveBeenCalledTimes(1); // the message was not sent again
    expect(runs.watchRun.mock.calls.at(-1)?.slice(0, 2)).toEqual(["r1", 2]);
    expect(result.current.state.chat.error).toBeNull();
    expect(result.current.state.chat.messages).toHaveLength(2);
    expect(result.current.state.chat.messages[1]?.parts).toEqual([
      { type: "text", text: "Hello there" },
    ]);
  });

  it("picks the run up again by itself when the browser says the network is back", async () => {
    const runs = runsThat(async (on) => {
      on(ev("token", 1, { text: "Hi " }));
    });
    let down = true;
    runs.watchRun.mockImplementation(async (_r, _s, _g, on) => {
      if (down) throw new TypeError("offline");
      on(ev("token", 2, { text: "again" }));
      on(DONE);
    });
    const { result } = renderHook(() =>
      useThreadChat({ runs, api: assistant, reconnect: { attempts: 2, delay: () => 1 } }),
    );
    await act(async () => result.current.send("hi"));
    expect(result.current.state.chat.error?.code).toBe("connection_lost");
    down = false;
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => expect(result.current.state.chat.phase).toBe("idle"));
    expect(result.current.state.chat.messages[1]?.parts).toEqual([
      { type: "text", text: "Hi again" },
    ]);
  });

  it("sends the message again when the engine refused the run (nothing to pick up)", async () => {
    const runs = runsThat(async (on) => {
      on(ev("error", 1, { code: "language_failed", message: "No answer.", retryable: true }));
    });
    const { result } = renderHook(() => useThreadChat({ runs, api: assistant }));
    await act(async () => result.current.send("hi"));
    await act(async () => result.current.retry());
    expect(runs.startRun).toHaveBeenCalledTimes(2);
    expect(runs.watchRun).not.toHaveBeenCalled();
  });
});

describe("ChatScreenNext", () => {
  it("shows Stop and Thinking while the answer is pending, and Stop reaches the engine", async () => {
    const runs = runsThat(
      (_on, signal) =>
        new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve())),
    );
    const user = userEvent.setup();
    render(<ChatScreenNext runs={runs} assistant={assistant} images={images} />);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello{Enter}");
    expect(await screen.findByText("Thinking…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Stop/ }));
    await waitFor(() => expect(runs.cancelRun).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Stop/ })).toBeNull());
    expect(screen.getByRole("textbox", { name: "Message" })).toBeEnabled();
  });

  it("lays text out right to left when it is written that way, in the box and in the bubble", async () => {
    const runs = runsThat(async (on) => {
      on(ev("token", 1, { text: "ok" }));
      on(DONE);
    });
    const user = userEvent.setup();
    render(<ChatScreenNext runs={runs} assistant={assistant} images={images} />);
    const box = screen.getByRole("textbox", { name: "Message" });
    expect(box).toHaveAttribute("dir", "auto");
    await user.type(box, "مرحبا{Enter}");
    const bubble = await screen.findByText("مرحبا");
    expect(bubble).toHaveAttribute("dir", "auto");
  });

  it("copies a reply, and puts a suggestion in the box for the person to send", async () => {
    const runs = runsThat(async (on) => {
      on(ev("token", 1, { text: "The answer." }));
      on(DONE);
    });
    const user = userEvent.setup();
    const write = vi.fn(async () => {});
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: write } });
    render(
      <ChatScreenNext
        runs={runs}
        assistant={assistant}
        images={images}
        examples={["Draw a fox"]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Draw a fox" }));
    const box = screen.getByRole("textbox", { name: "Message" });
    expect(box).toHaveValue("Draw a fox");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.click(await screen.findByRole("button", { name: "Copy reply" }));
    await waitFor(() => expect(write).toHaveBeenCalledWith("The answer."));
    vi.unstubAllGlobals();
  });

  it("keeps the same box element before and after the first message", async () => {
    const runs = runsThat(async (on) => {
      on(ev("token", 1, { text: "ok" }));
      on(DONE);
    });
    const user = userEvent.setup();
    render(<ChatScreenNext runs={runs} assistant={assistant} images={images} />);
    const before = screen.getByRole("textbox", { name: "Message" });
    await user.type(before, "hi{Enter}");
    await screen.findByText("ok");
    expect(screen.getByRole("textbox", { name: "Message" })).toBe(before);
    expect(before.isConnected).toBe(true);
  });

  it("registers the card of a question that needs an answer, so a paused run shows something", async () => {
    const runs = runsThat(async (on) => {
      on(ev("token", 1, { text: "Shall I?" }));
      on(
        ev("interrupt", 2, {
          interrupt_id: "i1",
          kind: "confirm_action",
          payload: { title: "Delete 3 pictures" },
        }),
      );
    });
    const user = userEvent.setup();
    render(<ChatScreenNext runs={runs} assistant={assistant} images={images} />);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "delete them{Enter}");
    expect(await screen.findByText("Delete 3 pictures")).toBeInTheDocument();
  });
});

describe("the screen reader", () => {
  it("is told that the assistant is answering, then once what it said", () => {
    const { rerender } = render(<Announcer working={false} error={null} answer="" />);
    expect(screen.getByRole("log")).toBeEmptyDOMElement();
    rerender(<Announcer working error={null} answer="" />);
    expect(screen.getByText("The assistant is answering.")).toBeInTheDocument();
    rerender(
      <Announcer working={false} error={null} answer={"A **fox** is [a dog](https://x.test)."} />,
    );
    expect(screen.getByText("Answer ready.")).toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveTextContent("The assistant said: A fox is a dog.");
  });

  it("says what went wrong instead of the answer", () => {
    const { rerender } = render(<Announcer working error={null} answer="" />);
    rerender(<Announcer working={false} error="No model is chosen." answer="" />);
    expect(screen.getByText("That did not work. No model is chosen.")).toBeInTheDocument();
    expect(screen.getByRole("log")).toBeEmptyDOMElement();
  });

  it("takes the marks of markdown out of what is read", () => {
    expect(
      plainText("# Title\n\n- one\n- two\n\n```ts\nlet x = 1;\n```\n`code` and **bold**"),
    ).toBe("Title one two let x = 1; code and bold");
  });
});

describe("toLikeMessage", () => {
  it("hands a finished call its result and a running one its progress, apart", () => {
    const running = toLikeMessage({
      id: "a",
      role: "assistant",
      streaming: true,
      parts: [
        {
          type: "tool",
          id: "t",
          name: "generate_image",
          arguments: {},
          status: "running",
          progress: 0.4,
          jobStatus: "running",
        },
      ],
    });
    expect(running.status).toEqual({ type: "running" });
    expect(running.content[0]).toMatchObject({ artifact: { progress: 0.4 }, isError: false });
    expect(running.content[0]).not.toHaveProperty("result");
    const done = toLikeMessage({
      id: "a",
      role: "assistant",
      parts: [
        {
          type: "tool",
          id: "t",
          name: "generate_image",
          arguments: {},
          status: "refused",
          output: { message: "No." },
        },
      ],
    });
    expect(done.content[0]).toMatchObject({
      result: { status: "refused", output: { message: "No." } },
      isError: false,
    });
  });
});
