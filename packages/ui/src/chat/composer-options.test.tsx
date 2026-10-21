// @vitest-environment jsdom
// The options bar and Thinking (ADR-0083, stage CO1), on both chat screens: the old one and the new one on assistant-ui.
import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, ImagesApi, OnEvent, ParsedEvent } from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatScreen } from "./ChatScreen";
import { useComposerOptions } from "./composer-options";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

const DONE = ev("done", { outputs: { status: "done", conversation_id: "c1", title: "T" } });

function runsThat(events: ParsedEvent[], inputs: object[] = []) {
  return {
    startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
      inputs.push(input);
      for (const e of events) on(e);
    }),
    watchRun: vi.fn(async () => {}),
  };
}

const saved: AssistantApi["get"] = async (id) => ({
  id,
  title: "Saved",
  created_at: "",
  updated_at: "",
  messages: [
    { id: "m1", seq: 1, role: "user", created_at: "", parts: [{ type: "text", text: "Why?" }] },
    {
      id: "m2",
      seq: 2,
      role: "assistant",
      created_at: "",
      parts: [
        { type: "reasoning", text: "Because of the stored thought." },
        { type: "text", text: "Because." },
      ],
    },
  ],
});
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
  get: saved,
  rename: async () => {
    throw new Error("unused");
  },
  remove: async () => {},
};
const images = { get: async () => ({}) } as unknown as ImagesApi;

beforeEach(() => {
  localStorage.clear();
});

describe("useComposerOptions", () => {
  it("offers Thinking only when the model can think, and starts with it off", () => {
    const none = renderHook(() => useComposerOptions(null, {}));
    expect(none.result.current.bar).toEqual([]);
    expect(none.result.current.runInput).toEqual({});
    const can = renderHook(() => useComposerOptions(null, { thinking: true }));
    expect(can.result.current.bar.map((o) => o.id)).toEqual(["thinking"]);
    expect(can.result.current.thinking).toBe(false);
    expect(can.result.current.runInput).toEqual({});
  });

  it("turns Thinking on for the next message, remembered per conversation", async () => {
    const { result, rerender } = renderHook(
      ({ id }) => useComposerOptions(id, { thinking: true }),
      {
        initialProps: { id: "a" as string | null },
      },
    );
    act(() => result.current.bar[0]?.onPress());
    expect(result.current.runInput).toEqual({ thinking: true });
    rerender({ id: "b" });
    await waitFor(() => expect(result.current.thinking).toBe(false)); // another conversation: its own choice
    rerender({ id: "a" });
    await waitFor(() => expect(result.current.thinking).toBe(true)); // and the first one remembers
  });

  it("keeps the choice made in a new chat when the chat gets its address", async () => {
    const { result, rerender } = renderHook(
      ({ id }) => useComposerOptions(id, { thinking: true }),
      {
        initialProps: { id: null as string | null },
      },
    );
    act(() => result.current.bar[0]?.onPress());
    rerender({ id: "c9" });
    await waitFor(() => expect(result.current.thinking).toBe(true));
    rerender({ id: null });
    rerender({ id: "c9" });
    await waitFor(() => expect(result.current.thinking).toBe(true)); // it was written under the new id
  });

  it("does not turn on for a model that cannot think, whatever was remembered", () => {
    localStorage.setItem("wasifyai.composer.options", JSON.stringify({ new: { thinking: true } }));
    const { result } = renderHook(() => useComposerOptions(null, {}));
    expect(result.current.thinking).toBe(false);
    expect(result.current.runInput).toEqual({});
  });
});

describe("the chat", () => {
  const Screen = ChatScreen;
  it("has no Thinking button for a model that cannot think", () => {
    render(<Screen runs={runsThat([])} assistant={assistant} images={images} />);
    expect(screen.queryByRole("button", { name: /^Thinking/ })).toBeNull();
  });

  it("sends nothing about thinking while it is off, and asks for it once it is on", async () => {
    const inputs: object[] = [];
    const runs = runsThat([ev("token", { text: "ok" }), DONE], inputs);
    const user = userEvent.setup();
    render(
      <Screen
        runs={runs}
        assistant={assistant}
        images={images}
        composerOptions={{ thinking: true }}
      />,
    );
    const button = screen.getByRole("button", { name: /^Thinking/ });
    expect(button).toHaveAttribute("aria-pressed", "false");
    await user.type(screen.getByRole("textbox", { name: "Message" }), "one{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(1));
    expect(inputs[0]).not.toHaveProperty("thinking");

    await user.click(screen.getByRole("button", { name: /^Thinking/ }));
    expect(screen.getByRole("button", { name: /^Thinking/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.type(screen.getByRole("textbox", { name: "Message" }), "two{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(2));
    expect(inputs[1]).toMatchObject({ text: "two", thinking: true });
  });

  it("shows a thinking turn's reasoning collapsed under Thinking, apart from the answer", async () => {
    const runs = runsThat([
      ev("reasoning", { text: "The person " }),
      ev("reasoning", { text: "wants a greeting." }),
      ev("token", { text: "Hello there." }),
      DONE,
    ]);
    const user = userEvent.setup();
    render(<Screen runs={runs} assistant={assistant} images={images} />);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hi{Enter}");
    expect(await screen.findByText("Hello there.")).toBeInTheDocument();
    const block = document.querySelector("details[data-reasoning]") as HTMLDetailsElement;
    expect(block).not.toBeNull();
    expect(block.open).toBe(false); // collapsed
    expect(within(block).getByText("Thinking")).toBeInTheDocument();
    await user.click(within(block).getByText("Thinking"));
    expect(block.open).toBe(true);
    expect(within(block).getByText("The person wants a greeting.")).toBeInTheDocument();
  });

  it("shows the thinking that was stored with a saved conversation, collapsed", async () => {
    render(
      <Screen runs={runsThat([])} assistant={assistant} images={images} conversationId="c5" />,
    );
    expect(await screen.findByText("Because.")).toBeInTheDocument();
    const block = document.querySelector("details[data-reasoning]") as HTMLDetailsElement;
    expect(block.open).toBe(false);
    expect(block).toHaveTextContent("Because of the stored thought.");
  });

  it("says a pending answer takes longer while Thinking is on", async () => {
    let release: () => void = () => {};
    const runs = {
      startRun: vi.fn(
        (_p: string, _i: object, _s: AbortSignal, _on: OnEvent) =>
          new Promise<void>((resolve) => {
            release = resolve;
          }),
      ),
      watchRun: vi.fn(async () => {}),
    };
    const user = userEvent.setup();
    render(
      <Screen
        runs={runs}
        assistant={assistant}
        images={images}
        composerOptions={{ thinking: true }}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^Thinking/ }));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hi{Enter}");
    expect(await screen.findByText(/takes longer than usual/)).toBeInTheDocument();
    release();
  });
});
