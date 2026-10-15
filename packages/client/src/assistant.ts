// The assistant (ADR-0057): conversations under `/products/wasifyai-assistant/conversations`, and the
// reducer that folds a turn's events into what a chat screen shows. The same code serves the web app and
// the desktop window; only the transport differs.
import type { ParsedEvent } from "./sse";
import { HttpError, type Transport, errorMessage } from "./transport";

export const ASSISTANT_PRODUCT = "wasifyai-assistant";

export type ConversationSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

/** A stored message part (the engine's own shape). */
export type StoredPart =
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | {
      type: "tool_result";
      id: string;
      name: string;
      status: ToolStatus;
      output: Record<string, unknown>;
      text?: string;
    };

export type StoredMessage = {
  id: string;
  seq: number;
  role: "user" | "assistant" | "tool";
  parts: StoredPart[];
  created_at: string;
};

export type Conversation = ConversationSummary & { messages: StoredMessage[] };

export type AssistantApi = {
  list(limit?: number): Promise<ConversationSummary[]>;
  get(id: string): Promise<Conversation>;
  rename(id: string, title: string): Promise<ConversationSummary>;
  remove(id: string): Promise<void>;
};

export function createAssistantApi(transport: Transport): AssistantApi {
  const base = `/products/${ASSISTANT_PRODUCT}/conversations`;
  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }
  return {
    async list(limit = 30) {
      const page = await json<{ conversations: ConversationSummary[] }>(`${base}?limit=${limit}`);
      return page.conversations;
    },
    get: (id) => json<Conversation>(`${base}/${encodeURIComponent(id)}`),
    rename: (id, title) =>
      json<ConversationSummary>(`${base}/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title }),
      }),
    async remove(id) {
      const res = await transport.fetch(`${base}/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!res.ok && res.status !== 404) throw new HttpError(res.status, await errorMessage(res));
    },
  };
}

// ---- what a chat screen shows ------------------------------------------------------------------

export type ToolStatus = "ok" | "refused" | "error";

export type ChatPart =
  | { type: "text"; text: string }
  | {
      type: "tool";
      id: string;
      name: string;
      arguments: Record<string, unknown>;
      /** running until its result arrives */
      status: "running" | ToolStatus;
      output?: Record<string, unknown>;
      /** a job's progress while it runs (an image being made) */
      progress?: number;
      jobStatus?: string;
      queuePosition?: number;
    };

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  parts: ChatPart[];
  /** the answer is still arriving */
  streaming?: boolean;
};

export type ChatError = { code: string; message: string; retryable: boolean };

export type ChatState = {
  conversationId: string | null;
  title: string;
  messages: ChatMessage[];
  phase: "idle" | "working" | "error";
  error: ChatError | null;
  runId: string | null;
  lastSeq: number;
};

export const initialChat: ChatState = {
  conversationId: null,
  title: "",
  messages: [],
  phase: "idle",
  error: null,
  runId: null,
  lastSeq: 0,
};

export type ChatAction =
  | { type: "submitted"; text: string; id: string }
  | { type: "event"; event: ParsedEvent }
  | { type: "failed"; message: string; retryable?: boolean; code?: string }
  | { type: "loaded"; conversation: Conversation }
  | { type: "reset" }
  | { type: "stopped" };

/** A stored conversation as the screen shows it: tool calls and their results fold into the
 * assistant message that made them, so a reload looks like the stream did. */
export function fromStored(messages: StoredMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  const results = new Map<string, Extract<StoredPart, { type: "tool_result" }>>();
  for (const m of messages) {
    for (const p of m.parts) if (p.type === "tool_result") results.set(p.id, p);
  }
  let current: ChatMessage | null = null;
  for (const m of messages) {
    if (m.role === "user") {
      current = null;
      out.push({
        id: m.id,
        role: "user",
        parts: m.parts.flatMap((p) =>
          p.type === "text" ? [{ type: "text" as const, text: p.text }] : [],
        ),
      });
    } else if (m.role === "assistant") {
      if (!current) {
        current = { id: m.id, role: "assistant", parts: [] };
        out.push(current);
      }
      for (const p of m.parts) {
        if (p.type === "text" && p.text) current.parts.push({ type: "text", text: p.text });
        if (p.type === "tool_call") {
          const r = results.get(p.id);
          current.parts.push({
            type: "tool",
            id: p.id,
            name: p.name,
            arguments: p.arguments,
            status: r ? r.status : "error",
            output: r?.output,
          });
        }
      }
    }
    // role "tool" messages only carry results, already folded in
  }
  return out;
}

function lastAssistant(messages: ChatMessage[]): ChatMessage | null {
  const last = messages[messages.length - 1];
  return last && last.role === "assistant" ? last : null;
}

function withLast(messages: ChatMessage[], fn: (m: ChatMessage) => ChatMessage): ChatMessage[] {
  const i = messages.length - 1;
  const last = messages[i];
  if (!last) return messages;
  return [...messages.slice(0, i), fn(last)];
}

function settle(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((m) => (m.streaming ? { ...m, streaming: false } : m));
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "reset":
      return initialChat;
    case "loaded":
      return {
        ...initialChat,
        conversationId: action.conversation.id,
        title: action.conversation.title,
        messages: fromStored(action.conversation.messages),
      };
    case "submitted":
      return {
        ...state,
        phase: "working",
        error: null,
        runId: null,
        lastSeq: 0,
        messages: [
          ...state.messages,
          { id: action.id, role: "user", parts: [{ type: "text", text: action.text }] },
          { id: `${action.id}-reply`, role: "assistant", parts: [], streaming: true },
        ],
      };
    case "stopped":
      return { ...state, phase: "idle", messages: settle(state.messages) };
    case "failed":
      return {
        ...state,
        phase: "error",
        messages: settle(state.messages),
        error: {
          code: action.code ?? "failed",
          message: action.message,
          retryable: action.retryable ?? true,
        },
      };
    case "event":
      return onEvent(state, action.event);
  }
}

function onEvent(state: ChatState, e: ParsedEvent): ChatState {
  const data = e.data as unknown as Record<string, unknown>;
  const seq = typeof data.seq === "number" ? data.seq : state.lastSeq;
  const base: ChatState = {
    ...state,
    runId: typeof data.run_id === "string" ? data.run_id : state.runId,
    lastSeq: Math.max(state.lastSeq, seq),
  };
  switch (e.event) {
    case "token": {
      const text = String(data.text ?? "");
      return {
        ...base,
        messages: withLast(base.messages, (m) => {
          if (m.role !== "assistant") return m;
          const parts = [...m.parts];
          const tail = parts[parts.length - 1];
          if (tail && tail.type === "text")
            parts[parts.length - 1] = { ...tail, text: tail.text + text };
          else parts.push({ type: "text", text });
          return { ...m, parts };
        }),
      };
    }
    case "tool_call":
      return {
        ...base,
        messages: withLast(base.messages, (m) => ({
          ...m,
          parts: [
            ...m.parts,
            {
              type: "tool",
              id: String(data.id),
              name: String(data.name),
              arguments: (data.arguments as Record<string, unknown>) ?? {},
              status: "running",
            },
          ],
        })),
      };
    case "job_progress":
      return {
        ...base,
        messages: withLast(base.messages, (m) => {
          const parts = [...m.parts];
          for (let i = parts.length - 1; i >= 0; i--) {
            const p = parts[i];
            if (p && p.type === "tool" && p.status === "running") {
              parts[i] = {
                ...p,
                jobStatus: String(data.status ?? ""),
                progress: typeof data.progress === "number" ? data.progress : p.progress,
                queuePosition:
                  typeof data.queue_position === "number" ? data.queue_position : p.queuePosition,
              };
              break;
            }
          }
          return { ...m, parts };
        }),
      };
    case "tool_result":
      return {
        ...base,
        messages: withLast(base.messages, (m) => ({
          ...m,
          parts: m.parts.map((p) =>
            p.type === "tool" && p.id === data.id
              ? {
                  ...p,
                  status: data.status as ToolStatus,
                  output: (data.output as Record<string, unknown>) ?? {},
                }
              : p,
          ),
        })),
      };
    case "done": {
      const out = (data.outputs as Record<string, unknown>) ?? {};
      if (out.status === "refused") {
        const refusal = (out.refusal as Record<string, string>) ?? {};
        return {
          ...base,
          phase: "error",
          messages: settle(
            base.messages.filter((m) => !(m.role === "assistant" && m.parts.length === 0)),
          ),
          error: {
            code: refusal.code ?? "refused",
            message: refusal.message ?? "That could not be sent.",
            retryable: false,
          },
        };
      }
      return {
        ...base,
        phase: "idle",
        conversationId:
          typeof out.conversation_id === "string" ? out.conversation_id : base.conversationId,
        title: typeof out.title === "string" && out.title ? out.title : base.title,
        messages: settle(base.messages),
      };
    }
    case "error":
      return {
        ...base,
        phase: "error",
        messages: settle(
          base.messages.filter((m) => !(m.role === "assistant" && m.parts.length === 0)),
        ),
        error: {
          code: String(data.code ?? "failed"),
          message: String(data.message ?? "Something went wrong."),
          retryable: Boolean(data.retryable),
        },
      };
    default:
      return base;
  }
}

export { lastAssistant };
