import { describe, expect, it } from "vitest";
import type { ChatMessage, Conversation } from "./assistant";
import { type TreeAction, type TreeState, initialTree, pathTo, treeReducer } from "./chat-tree";
import type { ParsedEvent } from "./sse";

const ev = (event: string, data: Record<string, unknown> = {}): TreeAction => ({
  type: "event",
  event: { event, data: { run_id: "r1", seq: 1, ...data } } as unknown as ParsedEvent,
});

const user = (id: string, text: string): ChatMessage => ({
  id,
  role: "user",
  parts: [{ type: "text", text }],
});

function run(actions: TreeAction[], from: TreeState = initialTree): TreeState {
  return actions.reduce(treeReducer, from);
}

const stored: Conversation = {
  id: "c1",
  title: "Foxes",
  created_at: "",
  updated_at: "",
  messages: [
    {
      id: "m1",
      seq: 1,
      role: "user",
      created_at: "",
      parts: [{ type: "text", text: "draw a fox" }],
    },
    {
      id: "m2",
      seq: 2,
      role: "assistant",
      created_at: "",
      parts: [
        { type: "text", text: "Drawing." },
        { type: "tool_call", id: "t1", name: "generate_image", arguments: { prompt: "a fox" } },
      ],
    },
    {
      id: "m3",
      seq: 3,
      role: "tool",
      created_at: "",
      parts: [
        {
          type: "tool_result",
          id: "t1",
          name: "generate_image",
          status: "ok",
          output: { image_id: "i1" },
        },
      ],
    },
    {
      id: "m4",
      seq: 4,
      role: "assistant",
      created_at: "",
      parts: [{ type: "text", text: "Done." }],
    },
    { id: "m5", seq: 5, role: "user", created_at: "", parts: [{ type: "text", text: "thanks" }] },
  ],
};

describe("treeReducer", () => {
  it("reads a stored conversation as one straight line, folding tool rows into the reply", () => {
    const s = run([{ type: "loaded", conversation: stored }]);
    expect(s.chat.conversationId).toBe("c1");
    expect(s.chat.title).toBe("Foxes");
    // the tool row and the reply that follows it are one assistant message, as on the old screen
    expect(s.chat.messages.map((m) => m.role)).toEqual(["user", "assistant", "user"]);
    expect(s.order).toEqual(["m1", "m2", "m5"]);
    expect(s.nodes.m1?.parentId).toBeNull();
    expect(s.nodes.m2?.parentId).toBe("m1");
    expect(s.nodes.m5?.parentId).toBe("m2");
    expect(s.headId).toBe("m5");
    const tool = s.chat.messages[1]?.parts[1];
    expect(tool && tool.type === "tool" && tool.status).toBe("ok");
  });

  it("begins a turn: the message, an empty streaming reply under it, and a working screen", () => {
    const s = run([
      { type: "loaded", conversation: stored },
      { type: "begin", user: user("u2", "again"), replyId: "r2", parentId: "m5" },
    ]);
    expect(s.chat.phase).toBe("working");
    expect(s.chat.messages.map((m) => m.id)).toEqual(["m1", "m2", "m5", "u2", "r2"]);
    expect(s.nodes.u2?.parentId).toBe("m5");
    expect(s.nodes.r2?.parentId).toBe("u2");
    expect(s.headId).toBe("r2");
    expect(s.chat.messages[4]?.streaming).toBe(true);
  });

  it("folds the turn's events into the reply and its node", () => {
    const s = run([
      { type: "begin", user: user("u1", "hi"), replyId: "r1", parentId: null },
      ev("token", { text: "Hel" }),
      ev("token", { text: "lo" }),
      ev("done", { outputs: { status: "done", conversation_id: "c9", title: "Hi" } }),
    ]);
    expect(s.chat.phase).toBe("idle");
    expect(s.chat.conversationId).toBe("c9");
    const reply = s.nodes.r1?.message;
    expect(reply?.parts).toEqual([{ type: "text", text: "Hello" }]);
    expect(reply?.streaming).toBe(false);
    expect(s.chat.messages[1]).toBe(reply);
  });

  it("takes the ids the engine stored the two messages under", () => {
    const s = run([
      { type: "begin", user: user("u1", "hi"), replyId: "r1", parentId: null },
      ev("token", { text: "Hello" }),
      ev("done", {
        outputs: {
          status: "done",
          conversation_id: "c9",
          user_message_id: "S1",
          assistant_message_id: "S2",
        },
      }),
    ]);
    expect(s.chat.messages.map((m) => m.id)).toEqual(["S1", "S2"]);
    expect(Object.keys(s.nodes).sort()).toEqual(["S1", "S2"]);
    expect(s.nodes.S2?.parentId).toBe("S1");
    expect(s.order).toEqual(["S1", "S2"]);
    expect(s.headId).toBe("S2");
    expect(pathTo(s.nodes, s.headId).map((m) => m.id)).toEqual(["S1", "S2"]);
  });

  it("keeps the ids as they are when the engine sends none (an older engine)", () => {
    const s = run([
      { type: "begin", user: user("u1", "hi"), replyId: "r1", parentId: null },
      ev("done", { outputs: { status: "done", conversation_id: "c9" } }),
    ]);
    expect(s.chat.messages.map((m) => m.id)).toEqual(["u1", "r1"]);
  });

  it("drops the node of a reply that failed before it said anything", () => {
    const s = run([
      { type: "begin", user: user("u1", "hi"), replyId: "r1", parentId: null },
      ev("error", { code: "language_failed", message: "No answer.", retryable: true }),
    ]);
    expect(s.chat.phase).toBe("error");
    expect(Object.keys(s.nodes)).toEqual(["u1"]);
    expect(s.order).toEqual(["u1"]);
    expect(s.headId).toBe("u1");
  });

  it("turns an interrupt into a waiting tool call and remembers the run to resume", () => {
    const s = run([
      { type: "begin", user: user("u1", "delete it"), replyId: "r1", parentId: null },
      ev("token", { text: "Shall I?" }),
      ev("interrupt", {
        interrupt_id: "i1",
        kind: "confirm_action",
        payload: { title: "Delete 3 pictures" },
        seq: 4,
      }),
    ]);
    expect(s.chat.phase).toBe("idle");
    expect(s.pendingRunId).toBe("r1");
    const reply = s.chat.messages[1];
    expect(reply?.streaming).toBe(false);
    const tool = reply?.parts[1];
    expect(tool).toMatchObject({
      type: "tool",
      id: "i1",
      name: "confirm_action",
      status: "running",
      approval: { id: "i1", kind: "confirm_action", runId: "r1", state: "pending" },
    });
    expect(s.nodes.r1?.message).toBe(reply);
  });

  it("resets to nothing", () => {
    const s = run([{ type: "loaded", conversation: stored }, { type: "reset" }]);
    expect(s).toBe(initialTree);
  });

  it("does not loop on a parent cycle", () => {
    const a = { id: "a", parentId: "b", message: user("a", "1") };
    const b = { id: "b", parentId: "a", message: user("b", "2") };
    expect(pathTo({ a, b }, "a").length).toBe(2);
  });
});
