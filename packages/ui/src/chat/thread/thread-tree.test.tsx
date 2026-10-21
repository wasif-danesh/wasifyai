// @vitest-environment jsdom
// Edit, answer again and the versions of a message (ADR-0082, stage CU2) on the new thread.
import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, Conversation, ImagesApi, OnEvent, ParsedEvent } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { ChatScreen } from "../ChatScreen";
import { useThreadChat } from "./use-thread-chat";

const ev = (event: string, seq: number, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq, ...data } }) as unknown as ParsedEvent;

const images = { get: async () => ({}) } as unknown as ImagesApi;

const row = (id: string, seq: number, role: "user" | "assistant", parent: string | null) => ({
  id,
  seq,
  role,
  created_at: "",
  parent_id: parent,
  parts: [{ type: "text" as const, text: `text of ${id}` }],
});

// u1 -> a1 -> u2 -> a2, and a2 answered again as a2b; the screen shows a2b
const saved: Conversation = {
  id: "c1",
  title: "Saved",
  created_at: "",
  updated_at: "",
  head_id: "a2b",
  messages: [
    row("u1", 1, "user", null),
    row("a1", 2, "assistant", "u1"),
    row("u2", 3, "user", "a1"),
    row("a2", 4, "assistant", "u2"),
    row("a2b", 5, "assistant", "u2"),
  ],
};

function api(over: Partial<AssistantApi> = {}): AssistantApi {
  return {
    options: async () => ({ thinking: false }),
    searchStatus: async () => {
      throw new Error("unused");
    },
    updateSearch: async () => {
      throw new Error("unused");
    },
    setHead: vi.fn(async () => {}),
    attach: async () => {
      throw new Error("unused");
    },
    unattach: async () => {},
    list: async () => [],
    get: vi.fn(async () => saved),
    rename: async () => {
      throw new Error("unused");
    },
    remove: async () => {},
    ...over,
  };
}

function runs(inputs: object[] = []) {
  return {
    startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
      inputs.push(input);
      on(ev("token", 1, { text: "fresh answer" }));
      on(
        ev("done", 2, {
          outputs: {
            status: "done",
            conversation_id: "c1",
            title: "Saved",
            user_message_id: (input as Record<string, string>).client_message_id ?? "u2",
            assistant_message_id: (input as Record<string, string>).client_reply_id,
          },
        }),
      );
    }),
    watchRun: vi.fn(async () => {}),
    cancelRun: vi.fn(async () => {}),
  };
}

describe("useThreadChat with branches", () => {
  it("opens a saved conversation as the whole tree, on the branch the engine says is on screen", async () => {
    const a = api();
    const { result } = renderHook(() =>
      useThreadChat({ runs: runs(), api: a, conversationId: "c1" }),
    );
    await waitFor(() => expect(result.current.state.headId).toBe("a2b"));
    expect(a.get).toHaveBeenCalledWith("c1", { tree: true });
    expect(result.current.state.chat.messages.map((m) => m.id)).toEqual(["u1", "a1", "u2", "a2b"]);
  });

  it("answers a message again under it, without asking it twice", async () => {
    const inputs: object[] = [];
    const { result } = renderHook(() =>
      useThreadChat({ runs: runs(inputs), api: api(), conversationId: "c1" }),
    );
    await waitFor(() => expect(result.current.state.headId).toBe("a2b"));
    await act(async () => result.current.regenerate("u2"));
    expect(inputs[0]).toMatchObject({
      conversation_id: "c1",
      parent_message_id: "u2",
      regenerate: true,
      client_reply_id: expect.any(String),
    });
    expect(inputs[0]).not.toHaveProperty("text");
    const msgs = result.current.state.chat.messages;
    expect(msgs.map((m) => m.role)).toEqual(["user", "assistant", "user", "assistant"]);
    expect(msgs[3]?.parts[0]).toMatchObject({ text: "fresh answer" });
    expect(Object.keys(result.current.state.nodes)).toHaveLength(6); // one new answer, the others kept
  });

  it("sends an edit under the old message's parent, and a new message under the end of the branch", async () => {
    const inputs: object[] = [];
    const { result } = renderHook(() =>
      useThreadChat({ runs: runs(inputs), api: api(), conversationId: "c1" }),
    );
    await waitFor(() => expect(result.current.state.headId).toBe("a2b"));
    await act(async () => result.current.send("two, better", { parentId: "a1" }));
    expect(inputs[0]).toMatchObject({ text: "two, better", parent_message_id: "a1" });
    await act(async () => result.current.send("and next"));
    expect(inputs[1]).toMatchObject({ text: "and next" });
    const head = result.current.state.nodes[result.current.state.headId ?? ""];
    expect(head?.message.role).toBe("assistant");
    // the first message can be edited too: its parent is "nothing"
    await act(async () => result.current.send("uno", { parentId: null }));
    expect(inputs[2]).toMatchObject({ text: "uno", parent_message_id: "" });
  });

  it("switches branch and tells the engine; Try again after a failed answer-again answers again", async () => {
    const a = api();
    const failing = {
      startRun: vi.fn(async (_p: string, _i: object, _s: AbortSignal, _on: OnEvent) => {
        throw new Error("down");
      }),
      watchRun: vi.fn(async () => {}),
    };
    const { result } = renderHook(() =>
      useThreadChat({
        runs: failing,
        api: a,
        conversationId: "c1",
        reconnect: { attempts: 1, delay: () => 1 },
      }),
    );
    await waitFor(() => expect(result.current.state.headId).toBe("a2b"));
    act(() => result.current.selectBranch("a2"));
    expect(result.current.state.chat.messages.at(-1)?.id).toBe("a2");
    expect(a.setHead).toHaveBeenCalledWith("c1", "a2");
    await act(async () => result.current.regenerate("u2"));
    expect(result.current.state.chat.phase).toBe("error");
    await act(async () => result.current.retry());
    expect(failing.startRun).toHaveBeenCalledTimes(2);
    expect(failing.startRun.mock.calls[1]?.[1]).toMatchObject({ regenerate: true });
  });
});

describe("the new thread", () => {
  it("shows which version of an answer is on screen, and moves between them", async () => {
    const a = api();
    const user = userEvent.setup();
    render(<ChatScreen runs={runs()} assistant={a} images={images} conversationId="c1" />);
    expect(await screen.findByText("text of a2b")).toBeInTheDocument();
    const pickers = screen.getAllByRole("group", { name: "Versions of this message" });
    expect(pickers).toHaveLength(1); // only the answer has more than one version
    expect(pickers[0]).toHaveTextContent("2 / 2");
    await user.click(screen.getByRole("button", { name: "Previous version" }));
    expect(await screen.findByText("text of a2")).toBeInTheDocument();
    expect(screen.queryByText("text of a2b")).toBeNull();
    expect(a.setHead).toHaveBeenCalledWith("c1", "a2");
  });

  it("edits a message: the box opens with its text, Send makes a new version under the same parent", async () => {
    const inputs: object[] = [];
    const user = userEvent.setup();
    render(
      <ChatScreen runs={runs(inputs)} assistant={api()} images={images} conversationId="c1" />,
    );
    await screen.findByText("text of a2b");
    const edits = screen.getAllByRole("button", { name: "Edit message" });
    await user.click(edits[1] as HTMLElement); // the second question
    const box = await screen.findByRole("textbox", { name: "Edit your message" });
    expect(box).toHaveValue("text of u2");
    await user.clear(box);
    await user.type(box, "a better question");
    await user.click(
      within(box.closest("form") as HTMLElement).getByRole("button", { name: "Send" }),
    );
    await waitFor(() => expect(inputs).toHaveLength(1));
    expect(inputs[0]).toMatchObject({ text: "a better question", parent_message_id: "a1" });
    expect(await screen.findByText("fresh answer")).toBeInTheDocument();
    expect(screen.getByText("a better question")).toBeInTheDocument();
    expect(screen.queryByText("text of u2")).toBeNull(); // the old question is the other version
  });

  it("answers again from the answer's own button", async () => {
    const inputs: object[] = [];
    const user = userEvent.setup();
    render(
      <ChatScreen runs={runs(inputs)} assistant={api()} images={images} conversationId="c1" />,
    );
    await screen.findByText("text of a2b");
    const buttons = screen.getAllByRole("button", { name: "Answer again" });
    await user.click(buttons[buttons.length - 1] as HTMLElement);
    await waitFor(() => expect(inputs).toHaveLength(1));
    expect(inputs[0]).toMatchObject({ regenerate: true, parent_message_id: "u2" });
  });
});
