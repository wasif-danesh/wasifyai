import { describe, expect, it } from "vitest";
import type { ChatMessage, Conversation } from "./assistant";
import {
  type TreeAction,
  type TreeState,
  initialTree,
  leafFrom,
  pathTo,
  siblingsOf,
  treeFromStored,
  treeReducer,
} from "./chat-tree";
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

// ---- the tree (stage CU2) ---------------------------------------------------------------------

const row = (
  id: string,
  seq: number,
  role: "user" | "assistant" | "tool",
  parent: string | null,
  text = id,
): Conversation["messages"][number] => ({
  id,
  seq,
  role,
  created_at: "",
  parent_id: parent,
  parts: role === "tool" ? [] : [{ type: "text", text }],
});

// one: u1 -> a1 (tool call) -> t1 -> a1b ; two: u2 -> a2 ; two edited: u2b -> a2b ; a2 answered again: a2c
const forked: Conversation = {
  id: "c1",
  title: "T",
  created_at: "",
  updated_at: "",
  head_id: "a2b",
  messages: [
    row("u1", 1, "user", null),
    row("a1", 2, "assistant", "u1"),
    row("t1", 3, "tool", "a1"),
    row("a1b", 4, "assistant", "t1"),
    row("u2", 5, "user", "a1b"),
    row("a2", 6, "assistant", "u2"),
    row("u2b", 7, "user", "a1b"),
    row("a2b", 8, "assistant", "u2b"),
    row("a2c", 9, "assistant", "u2"),
  ],
};

describe("treeFromStored", () => {
  it("folds a turn's rows into one node named by its first row, and keeps the branches", () => {
    const { nodes, order, headId } = treeFromStored(forked.messages, forked.head_id);
    expect(order).toEqual(["u1", "a1", "u2", "a2", "u2b", "a2b", "a2c"]);
    expect(nodes.a1?.message.parts.map((p) => p.type)).toEqual(["text", "text"]); // a1 and a1b are one node
    expect(nodes.u2?.parentId).toBe("a1");
    expect(nodes.u2b?.parentId).toBe("a1"); // the edit is a sibling of the question it replaced
    expect(nodes.a2c?.parentId).toBe("u2"); // an answer made again is a sibling of the first
    expect(headId).toBe("a2b");
  });

  it("shows the branch the engine says is on screen, and the whole path to it", () => {
    const s = run([{ type: "loaded", conversation: forked }]);
    expect(s.chat.messages.map((m) => m.id)).toEqual(["u1", "a1", "u2b", "a2b"]);
    expect(s.headId).toBe("a2b");
    const other = run([{ type: "loaded", conversation: { ...forked, head_id: "a2c" } }]);
    expect(other.chat.messages.map((m) => m.id)).toEqual(["u1", "a1", "u2", "a2c"]);
  });

  it("names the head by any row of its turn (the engine may send the last row of a tool turn)", () => {
    const { headId } = treeFromStored(forked.messages, "a1b");
    expect(headId).toBe("a1");
  });

  it("reads a conversation from before the tree as a chain, and ignores a head it does not know", () => {
    const legacy = stored.messages; // no parent ids at all
    const { nodes, headId } = treeFromStored(legacy, "gone");
    expect(Object.keys(nodes)).toEqual(["m1", "m2", "m5"]);
    expect(nodes.m5?.parentId).toBe("m2");
    expect(headId).toBe("m5");
  });

  it("finds siblings and the end of a branch", () => {
    const t = treeFromStored(forked.messages, forked.head_id);
    expect(siblingsOf(t, "u2")).toEqual(["u2", "u2b"]);
    expect(siblingsOf(t, "a2c")).toEqual(["a2", "a2c"]);
    expect(siblingsOf(t, "u1")).toEqual(["u1"]);
    expect(leafFrom(t, "u2")).toBe("a2c"); // the newest answer
    expect(leafFrom(t, "a1")).toBe("a2b"); // down the newest branch
  });
});

describe("branching in the reducer", () => {
  const loaded = () => run([{ type: "loaded", conversation: forked }]);

  it("an edit goes under the parent of the message it replaces, and the old branch stays", () => {
    const s = run(
      [
        {
          type: "begin",
          user: user("u2c", "two again"),
          replyId: "a2d",
          parentId: "a1",
        },
      ],
      loaded(),
    );
    expect(s.chat.messages.map((m) => m.id)).toEqual(["u1", "a1", "u2c", "a2d"]);
    expect(s.nodes.u2?.parentId).toBe("a1");
    expect(siblingsOf(s, "u2c")).toEqual(["u2", "u2b", "u2c"]);
    expect(s.headId).toBe("a2d");
  });

  it("answering again adds a reply under the same question and no new question", () => {
    const s = run([{ type: "begin", user: null, replyId: "a2d", parentId: "u2" }], loaded());
    expect(s.chat.messages.map((m) => m.id)).toEqual(["u1", "a1", "u2", "a2d"]);
    expect(s.nodes.a2d?.parentId).toBe("u2");
    expect(s.chat.phase).toBe("working");
    expect(Object.keys(s.nodes)).toHaveLength(8);
  });

  it("switching branch shows the path to the end of that branch, and not while an answer is coming", () => {
    const s = run([{ type: "head", headId: "u2" }], loaded());
    expect(s.chat.messages.map((m) => m.id)).toEqual(["u1", "a1", "u2", "a2c"]);
    expect(s.headId).toBe("a2c");
    const busy = run([{ type: "begin", user: null, replyId: "x", parentId: "u2" }], loaded());
    expect(run([{ type: "head", headId: "u2b" }], busy)).toBe(busy);
    expect(run([{ type: "head", headId: "nope" }], loaded()).headId).toBe("a2b");
  });
});

// ---- approvals (stage CU2) --------------------------------------------------------------------

describe("a card that waits for the person", () => {
  const card = {
    type: "interrupt" as const,
    kind: "confirm_action",
    status: "pending" as const,
    tool_call_id: "t1",
    approval_id: "ap1",
    run_id: "r9",
    title: "Make a picture",
    summary: "Make a picture",
    params: { prompt: "a fox" },
  };
  const waiting: Conversation = {
    id: "c1",
    title: "T",
    created_at: "",
    updated_at: "",
    head_id: "t",
    messages: [
      row("u", 1, "user", null),
      {
        ...row("a", 2, "assistant", "u"),
        parts: [
          { type: "tool_call", id: "t1", name: "generate_image", arguments: { prompt: "a fox" } },
        ],
      },
      { ...row("t", 3, "tool", "a"), parts: [card] },
    ],
  };

  it("is read from a stored conversation as a waiting tool call, and the run to answer is remembered", () => {
    const s = run([{ type: "loaded", conversation: waiting }]);
    const tool = s.chat.messages[1]?.parts[0];
    expect(tool).toMatchObject({
      type: "tool",
      id: "t1",
      status: "running",
      approval: { id: "ap1", runId: "r9", state: "pending", title: "Make a picture" },
    });
    expect(s.pendingRunId).toBe("r9");
  });

  it("shows the answer once it was given, and the result when there is one", () => {
    const decided: Conversation = {
      ...waiting,
      messages: [
        ...waiting.messages.slice(0, 2),
        {
          ...row("t", 3, "tool", "a"),
          parts: [
            { ...card, status: "approved" },
            {
              type: "tool_result",
              id: "t1",
              name: "generate_image",
              status: "ok",
              output: { image_id: "i1" },
            },
          ],
        },
      ],
    };
    const s = run([{ type: "loaded", conversation: decided }]);
    expect(s.chat.messages[1]?.parts[0]).toMatchObject({
      status: "ok",
      approval: { state: "approved" },
    });
    expect(s.pendingRunId).toBeNull();
  });

  it("puts a live card on the tool call it is about, and answering it sets the run going again", () => {
    let s = run([
      { type: "begin", user: user("u", "draw"), replyId: "a", parentId: null },
      ev("tool_call", { id: "t1", name: "generate_image", arguments: { prompt: "a fox" } }),
      ev("interrupt", {
        interrupt_id: "i7",
        kind: "confirm_action",
        payload: {
          kind: "confirm_action",
          tool_call_id: "t1",
          title: "Make a picture",
          params: { prompt: "a fox" },
        },
      }),
    ]);
    const reply = s.chat.messages[1];
    expect(reply?.parts).toHaveLength(1); // not a second part
    expect(reply?.parts[0]).toMatchObject({
      name: "generate_image",
      status: "running",
      approval: { runId: "r1", state: "pending", title: "Make a picture" },
    });
    expect(s.chat.phase).toBe("idle");
    expect(s.pendingRunId).toBe("r1");

    s = run([{ type: "answered", approved: true }], s);
    expect(s.chat.phase).toBe("working");
    expect(s.chat.messages[1]?.streaming).toBe(true);
    expect(s.chat.messages[1]?.parts[0]).toMatchObject({ approval: { state: "approved" } });
    expect(s.pendingRunId).toBeNull();
    s = run(
      [
        ev("tool_result", { id: "t1", status: "ok", output: { image_id: "i1" } }),
        ev("token", { text: "Here." }),
      ],
      s,
    );
    expect(s.chat.messages[1]?.parts[0]).toMatchObject({ status: "ok" });
    expect(s.chat.messages[1]?.parts[1]).toMatchObject({ type: "text", text: "Here." });
  });
});
