// The chat as a tree of messages (ADR-0082, stage CU2). Every message has a parent; a message with a second child is a branch:
// an edited message is a sibling of the one it replaced, and an answer made again is a sibling of the answer it replaced.
// User and assistant messages only; a tool's result is a part of the assistant message that called it. The engine stores
// several rows for one assistant turn (the call, the tool's results, the answer); they are folded into one node here, named
// by the turn's first row, which is the id the engine accepts as a parent.
//
// `chatReducer` (assistant.ts) still folds the events of the turn that is running; this reducer keeps the nodes around it.
import {
  type ChatAction,
  type ChatMessage,
  type ChatPart,
  type ChatState,
  type Conversation,
  type StoredMessage,
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
  /** the person's message and the reply about to stream under it; no `user` = the reply is made again under `parentId` */
  | { type: "begin"; user: ChatMessage | null; replyId: string; parentId: string | null }
  /** show the branch that ends at (or below) this node */
  | { type: "head"; headId: string }
  /** the person answered the card that waits on this branch */
  | { type: "answered"; approved: boolean }
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

/** The nodes of a stored conversation. Rows of one assistant turn become one node (named by its first row); an engine from
 * before the tree sends no parents, and then each row follows the one before it. `headRow` is the last row of the branch on
 * screen; without it the last node is the head. */
export function treeFromStored(
  messages: StoredMessage[],
  headRow?: string | null,
): { nodes: Record<string, TreeNode>; order: string[]; headId: string | null } {
  const rows = [...messages].sort((a, b) => a.seq - b.seq);
  const chain = rows.length > 0 && rows.every((r) => r.parent_id === undefined);
  const parentOf = (r: StoredMessage, i: number): string | null =>
    chain ? (i === 0 ? null : (rows[i - 1] as StoredMessage).id) : (r.parent_id ?? null);
  const byId = new Map(rows.map((r) => [r.id, r]));
  const nodeOf = new Map<string, string>();
  const turnRows = new Map<string, StoredMessage[]>();
  const first = new Map<string, number>();
  rows.forEach((r, i) => {
    const parent = parentOf(r, i);
    const parentRow = parent ? byId.get(parent) : undefined;
    if (r.role === "user") {
      nodeOf.set(r.id, r.id);
      turnRows.set(r.id, [r]);
      first.set(r.id, i);
    } else if (parentRow && parentRow.role !== "user" && nodeOf.has(parentRow.id)) {
      const id = nodeOf.get(parentRow.id) as string; // the next row of the same turn
      nodeOf.set(r.id, id);
      turnRows.get(id)?.push(r);
    } else {
      nodeOf.set(r.id, r.id);
      turnRows.set(r.id, [r]);
      first.set(r.id, i);
    }
  });
  const nodes: Record<string, TreeNode> = {};
  const order = [...turnRows.keys()].sort((a, b) => (first.get(a) ?? 0) - (first.get(b) ?? 0));
  for (const id of order) {
    const own = turnRows.get(id) as StoredMessage[];
    const message = fromStored(own)[0];
    if (!message) continue;
    const top = own[0] as StoredMessage;
    const parent = parentOf(top, first.get(id) ?? 0);
    nodes[id] = {
      id,
      parentId: parent ? (nodeOf.get(parent) ?? null) : null,
      message: { ...message, id },
    };
  }
  const kept = order.filter((id) => nodes[id]);
  const head = (headRow && nodeOf.get(headRow)) || kept[kept.length - 1] || null;
  return { nodes, order: kept, headId: head };
}

/** The run that waits for an answer to a card on this path (the last message's pending card), if any. */
export function pendingRunOf(path: ChatMessage[]): string | null {
  const last = path[path.length - 1];
  if (!last || last.role !== "assistant") return null;
  for (const p of last.parts)
    if (p.type === "tool" && p.approval?.state === "pending") return p.approval.runId;
  return null;
}

/** The newest descendant of a node: where a branch ends (the newest child each time). */
export function leafFrom(s: Pick<TreeState, "nodes" | "order">, id: string): string {
  const children = new Map<string, string>();
  for (const k of s.order) {
    const n = s.nodes[k];
    if (n?.parentId) children.set(n.parentId, k); // later nodes win: the newest child
  }
  let cur = id;
  const seen = new Set<string>();
  for (;;) {
    const next = children.get(cur);
    if (!next || seen.has(cur)) return cur;
    seen.add(cur);
    cur = next;
  }
}

/** The siblings of a node (the messages with the same parent, oldest first), itself included. */
export function siblingsOf(s: Pick<TreeState, "nodes" | "order">, id: string): string[] {
  const me = s.nodes[id];
  if (!me) return [];
  return s.order.filter((k) => s.nodes[k]?.parentId === me.parentId);
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
  const payload = (d.payload as Record<string, unknown>) ?? {};
  const approval = {
    id: String(d.interrupt_id),
    kind: String(d.kind ?? "interrupt"),
    runId,
    state: "pending" as const,
    title: typeof payload.title === "string" ? payload.title : undefined,
    summary: typeof payload.summary === "string" ? payload.summary : undefined,
    params:
      payload.params && typeof payload.params === "object"
        ? (payload.params as Record<string, unknown>)
        : undefined,
  };
  // the card belongs to the tool call it is about, when the engine names one
  const callId = typeof payload.tool_call_id === "string" ? payload.tool_call_id : null;
  const target = callId ? last.parts.find((p) => p.type === "tool" && p.id === callId) : undefined;
  if (target) {
    const parts = last.parts.map((p) =>
      p === target && p.type === "tool" ? { ...p, approval } : p,
    );
    const message: ChatMessage = { ...last, streaming: false, parts };
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
        messages: [...s.chat.messages.slice(0, -1), message],
      },
    };
  }
  const part: ChatPart = {
    type: "tool",
    id: String(d.interrupt_id),
    name: String(d.kind ?? "interrupt"),
    arguments: payload,
    status: "running",
    approval,
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
      const { nodes, order, headId } = treeFromStored(
        a.conversation.messages,
        a.conversation.head_id,
      );
      return {
        chat: {
          ...initialChat,
          conversationId: a.conversation.id,
          title: a.conversation.title,
          messages: pathTo(nodes, headId),
        },
        nodes,
        order,
        headId,
        pendingRunId: pendingRunOf(pathTo(nodes, headId)),
      };
    }
    case "answered": {
      // the person clicked the card: show the answer on it, and the turn goes on
      const last = s.chat.messages[s.chat.messages.length - 1];
      if (!last || last.role !== "assistant") return s;
      const parts = last.parts.map((p) =>
        p.type === "tool" && p.approval?.state === "pending"
          ? {
              ...p,
              approval: {
                ...p.approval,
                state: a.approved ? ("approved" as const) : ("declined" as const),
              },
            }
          : p,
      );
      const message: ChatMessage = { ...last, parts, streaming: true };
      const node = s.nodes[last.id];
      return {
        ...s,
        pendingRunId: null,
        nodes: node ? { ...s.nodes, [last.id]: { ...node, message } } : s.nodes,
        chat: {
          ...s.chat,
          phase: "working",
          error: null,
          messages: [...s.chat.messages.slice(0, -1), message],
        },
      };
    }
    case "head": {
      // the person picked another branch: show the path to the node, down to the end of that branch
      if (!s.nodes[a.headId] || s.chat.phase === "working") return s;
      const leaf = leafFrom(s, a.headId);
      return { ...s, headId: leaf, chat: { ...s.chat, messages: pathTo(s.nodes, leaf) } };
    }
    case "begin": {
      const reply: ChatMessage = { id: a.replyId, role: "assistant", parts: [], streaming: true };
      // the reply streams under the new message, or under the one being answered again
      const user = a.user;
      const withUser = user ? upsert(s, { id: user.id, parentId: a.parentId, message: user }) : s;
      const under = user ? user.id : a.parentId;
      const next = upsert(withUser, { id: reply.id, parentId: under, message: reply });
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
          messages: [...pathTo(s.nodes, a.parentId), ...(user ? [user] : []), reply],
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
