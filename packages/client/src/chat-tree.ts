// The chat as a tree of messages (ADR-0082). The engine stores one straight line today, so a conversation is a chain: every
// message has the one before it as its parent. The tree is there so that edit, regenerate and the branch picker (stage CU2)
// only add: a message with a second child is a branch. User and assistant messages only; a tool's result is a part of the
// assistant message that called it.
//
// `chatReducer` (assistant.ts) still folds the events of the turn that is running; this reducer keeps the nodes around it.
import {
  type ChatAction,
  type ChatMessage,
  type ChatPart,
  type ChatState,
  type Conversation,
  chatReducer,
  fromStored,
  initialChat,
} from "./assistant";
import type { ParsedEvent } from "./sse";

export type TreeNode = { id: string; parentId: string | null; message: ChatMessage };

export type TreeState = {
  /** the turn on screen: `chat.messages` is the active path (node ids are message ids) */
  chat: ChatState;
  nodes: Record<string, TreeNode>;
  /** node ids in the order they were added */
  order: string[];
  /** the last message of the active path */
  headId: string | null;
  /** an `interrupt` is waiting for an answer on this run */
  pendingRunId: string | null;
};

export const initialTree: TreeState = {
  chat: initialChat,
  nodes: {},
  order: [],
  headId: null,
  pendingRunId: null,
};

export type TreeAction =
  | { type: "chat"; action: ChatAction }
  | { type: "event"; event: ParsedEvent }
  | { type: "loaded"; conversation: Conversation }
  | { type: "begin"; user: ChatMessage; replyId: string; parentId: string | null }
  | { type: "reset" };

/** The active path: the node `leafId` and its ancestors, oldest first. */
export function pathTo(nodes: Record<string, TreeNode>, leafId: string | null): ChatMessage[] {
  const out: ChatMessage[] = [];
  const seen = new Set<string>();
  let cur = leafId ? nodes[leafId] : undefined;
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    out.unshift(cur.message);
    cur = cur.parentId ? nodes[cur.parentId] : undefined;
  }
  return out;
}

/** The nodes of the stored conversation as a chain: today's engine sends no parent, so each message follows the one before. */
function chainOf(messages: ChatMessage[]): TreeNode[] {
  return messages.map((message, i) => ({
    id: message.id,
    parentId: i === 0 ? null : (messages[i - 1] as ChatMessage).id,
    message,
  }));
}

function upsert(s: TreeState, node: TreeNode): TreeState {
  return {
    ...s,
    nodes: { ...s.nodes, [node.id]: node },
    order: s.nodes[node.id] ? s.order : [...s.order, node.id],
  };
}

/** Give the two messages of the turn the ids the engine stored them under, when they differ from the ones chosen here. */
function renameIds(s: TreeState, ids: Record<string, string>): TreeState {
  if (!Object.entries(ids).some(([from, to]) => from !== to && s.nodes[from])) return s;
  const re = (id: string) => ids[id] ?? id;
  const nodes: Record<string, TreeNode> = {};
  for (const n of Object.values(s.nodes)) {
    nodes[re(n.id)] = {
      id: re(n.id),
      parentId: n.parentId ? re(n.parentId) : null,
      message: { ...n.message, id: re(n.id) },
    };
  }
  const messages = s.chat.messages.map((m) => (ids[m.id] ? { ...m, id: re(m.id) } : m));
  return {
    ...s,
    nodes,
    order: s.order.map(re),
    headId: s.headId ? re(s.headId) : null,
    chat: { ...s.chat, messages },
  };
}

/** After the turn's messages changed, keep their nodes in step (and drop the node of a reply that was dropped). */
function syncNodes(s: TreeState, before: ChatState, chat: ChatState): TreeState {
  let nodes = s.nodes;
  let order = s.order;
  for (const m of chat.messages) {
    const n = nodes[m.id];
    if (n && n.message !== m) nodes = { ...nodes, [m.id]: { ...n, message: m } };
  }
  const kept = new Set(chat.messages.map((m) => m.id));
  for (const m of before.messages) {
    if (!kept.has(m.id) && nodes[m.id]) {
      const { [m.id]: _gone, ...rest } = nodes;
      nodes = rest;
      order = order.filter((k) => k !== m.id);
    }
  }
  const last = chat.messages[chat.messages.length - 1];
  return { ...s, chat, nodes, order, headId: last ? last.id : s.headId };
}

function interrupted(s: TreeState, e: ParsedEvent): TreeState {
  const d = e.data as unknown as Record<string, unknown>;
  const last = s.chat.messages[s.chat.messages.length - 1];
  if (!last || last.role !== "assistant") return s;
  const runId = String(d.run_id ?? s.chat.runId ?? "");
  const part: ChatPart = {
    type: "tool",
    id: String(d.interrupt_id),
    name: String(d.kind ?? "interrupt"),
    arguments: (d.payload as Record<string, unknown>) ?? {},
    status: "running",
    approval: {
      id: String(d.interrupt_id),
      kind: String(d.kind ?? "interrupt"),
      runId,
      state: "pending",
    },
  };
  const message: ChatMessage = { ...last, streaming: false, parts: [...last.parts, part] };
  const messages = [...s.chat.messages.slice(0, -1), message];
  const node = s.nodes[last.id];
  return {
    ...s,
    pendingRunId: runId,
    nodes: node ? { ...s.nodes, [last.id]: { ...node, message } } : s.nodes,
    chat: {
      ...s.chat,
      phase: "idle",
      runId,
      lastSeq: Math.max(s.chat.lastSeq, typeof d.seq === "number" ? d.seq : 0),
      messages,
    },
  };
}

export function treeReducer(s: TreeState, a: TreeAction): TreeState {
  switch (a.type) {
    case "reset":
      return initialTree;
    case "loaded": {
      const nodes: Record<string, TreeNode> = {};
      const order: string[] = [];
      const chain = chainOf(fromStored(a.conversation.messages));
      for (const n of chain) {
        nodes[n.id] = n;
        order.push(n.id);
      }
      const headId = chain.length ? (chain[chain.length - 1] as TreeNode).id : null;
      const messages = pathTo(nodes, headId);
      return {
        chat: {
          ...initialChat,
          conversationId: a.conversation.id,
          title: a.conversation.title,
          messages,
        },
        nodes,
        order,
        headId,
        // a stored interrupt is read in stage CU2 (the engine does not store one yet)
        pendingRunId: null,
      };
    }
    case "begin": {
      // the person's message and the reply that is about to stream under it
      const withUser = upsert(s, { id: a.user.id, parentId: a.parentId, message: a.user });
      const reply: ChatMessage = { id: a.replyId, role: "assistant", parts: [], streaming: true };
      const next = upsert(withUser, { id: reply.id, parentId: a.user.id, message: reply });
      return {
        ...next,
        headId: reply.id,
        pendingRunId: null,
        chat: {
          ...s.chat,
          phase: "working",
          error: null,
          runId: null,
          lastSeq: 0,
          messages: [...pathTo(s.nodes, a.parentId), a.user, reply],
        },
      };
    }
    case "chat": {
      const chat = chatReducer(s.chat, a.action);
      return syncNodes(s, s.chat, chat);
    }
    case "event": {
      if (a.event.event === "interrupt") return interrupted(s, a.event);
      const next = treeReducer(s, { type: "chat", action: { type: "event", event: a.event } });
      if (a.event.event !== "done") return next;
      // the engine says which ids it stored the turn's two messages under
      const out = ((a.event.data as unknown as Record<string, unknown>).outputs ?? {}) as Record<
        string,
        unknown
      >;
      const user = s.chat.messages[s.chat.messages.length - 2];
      const reply = s.chat.messages[s.chat.messages.length - 1];
      const ids: Record<string, string> = {};
      if (user && typeof out.user_message_id === "string") ids[user.id] = out.user_message_id;
      if (reply && typeof out.assistant_message_id === "string")
        ids[reply.id] = out.assistant_message_id;
      return renameIds(next, ids);
    }
  }
}
