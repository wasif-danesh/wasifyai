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
  /** the model's thinking (ADR-0083); shown collapsed, never given back to the model */
  | { type: "reasoning"; text: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  /** a file attached to a message (ADR-0083, CO2); a picture has a short-lived `url` when the engine read the chat */
  | {
      type: "attachment";
      kind: "image" | "document";
      id: string;
      key?: string;
      name: string;
      bytes?: number;
      url?: string;
    }
  /** a card that waits for the person's answer (ADR-0071): stored when the turn parks, updated when it is answered */
  | {
      type: "interrupt";
      kind: string;
      status: "pending" | "approved" | "declined";
      tool_call_id: string;
      approval_id?: string;
      run_id: string;
      title?: string;
      summary?: string;
      params?: Record<string, unknown>;
    }
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
  /** the message this one follows; empty for a first message (an engine from before the tree sends none: a chain) */
  parent_id?: string | null;
};

export type Conversation = ConversationSummary & {
  messages: StoredMessage[];
  /** the last message of the branch on screen */
  head_id?: string | null;
};

/** Web search as the chat box sees it (ADR-0083): whether there is a Search button, and what pressing it must ask. */
export type SearchOptions = {
  /** this engine can search at all */
  available: boolean;
  /** the person allowed searching with the service named below */
  consented: boolean;
  /** allowed, and the service has its key */
  ready: boolean;
  provider: string;
  provider_title: string;
  consent_text: string;
  /** the chosen service needs a key that is not saved yet */
  needs_key: boolean;
};

/** Attaching files (ADR-0083, CO2): what the engine keeps and the model in use reads. */
export type AttachOptions = {
  available: boolean;
  /** the model reads pictures (null: not known, so a picture is tried) */
  images: boolean | null;
  documents: boolean;
  /** why a picture will not work, in words, when it will not */
  images_note: string;
};

/** What the chat box can offer with the model in use (ADR-0083). */
export type ChatOptions = { thinking: boolean; search?: SearchOptions; attach?: AttachOptions };

/** A file that was sent to the engine and waits to be attached to the next message. */
export type UploadedAttachment = {
  id: string;
  kind: "image" | "document";
  name: string;
  chars?: number;
  pages?: number;
  width?: number;
  height?: number;
  /** a document longer than the engine keeps */
  truncated?: boolean;
};

export type SearchProvider = {
  id: string;
  title: string;
  needs_key: boolean;
  key_set: boolean;
  key_url: string;
  sends_to: string;
  note: string;
};

/** The web search settings. A key is written, never read back: only whether one is saved. */
export type SearchStatus = {
  provider: string;
  consented: boolean;
  consent_text: string;
  can_save_keys: boolean;
  providers: SearchProvider[];
};

export type SearchUpdate = {
  provider?: string;
  consent?: boolean;
  key?: { provider: string; value: string };
  remove_key?: string;
};

export type AssistantApi = {
  options(): Promise<ChatOptions>;
  searchStatus(): Promise<SearchStatus>;
  updateSearch(update: SearchUpdate): Promise<SearchStatus>;
  /** Send a picture (PNG, JPEG, WebP) or a document to the engine to attach to the next message. Refused in words. */
  attach(file: Blob, name: string): Promise<UploadedAttachment>;
  /** Take back a file that was sent but not used. Failures are not worth showing: the engine clears unused ones after a day. */
  unattach(id: string): Promise<void>;
  list(limit?: number): Promise<ConversationSummary[]>;
  /** One conversation: the branch on screen, or with `tree` every message of every branch. */
  get(id: string, opts?: { tree?: boolean }): Promise<Conversation>;
  /** Remember which branch is on screen (any message of it; the engine keeps the end of that turn). */
  setHead(id: string, messageId: string): Promise<void>;
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
    options: () => json<ChatOptions>(`/products/${ASSISTANT_PRODUCT}/options`),
    searchStatus: () => json<SearchStatus>(`/products/${ASSISTANT_PRODUCT}/search`),
    updateSearch: (update) =>
      json<SearchStatus>(`/products/${ASSISTANT_PRODUCT}/search`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(update),
      }),
    async attach(file, name) {
      const kind = /^image\/(png|jpeg|webp)$/.test(file.type) ? "image" : "document";
      const product = `/products/${ASSISTANT_PRODUCT}`;
      if (kind === "image") {
        const r = await json<{ upload_id: string; width: number; height: number }>(
          `${product}/uploads/images`,
          { method: "POST", headers: { "content-type": file.type }, body: file },
        );
        return { id: r.upload_id, kind, name, width: r.width, height: r.height };
      }
      const r = await json<{
        id: string;
        name: string;
        chars: number;
        pages: number | null;
        truncated: boolean;
      }>(`${product}/attachments`, {
        method: "POST",
        headers: {
          "content-type": file.type || "application/octet-stream",
          "x-file-name": encodeURIComponent(name),
        },
        body: file,
      });
      return {
        id: r.id,
        kind,
        name: r.name,
        chars: r.chars,
        pages: r.pages ?? undefined,
        truncated: r.truncated,
      };
    },
    async unattach(id) {
      try {
        await transport.fetch(
          `/products/${ASSISTANT_PRODUCT}/uploads/images/${encodeURIComponent(id)}`,
          {
            method: "DELETE",
          },
        );
      } catch {
        // cleared by the engine after a day
      }
    },
    async list(limit = 30) {
      const page = await json<{ conversations: ConversationSummary[] }>(`${base}?limit=${limit}`);
      return page.conversations;
    },
    get: (id, opts) =>
      json<Conversation>(`${base}/${encodeURIComponent(id)}${opts?.tree ? "?tree=1" : ""}`),
    async setHead(id, messageId) {
      await json<ConversationSummary>(`${base}/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ head_id: messageId }),
      });
    },
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

/** A tool call that waits for the person's answer (an `interrupt` event: the `confirm_action` card of ADR-0071). */
export type ToolApproval = {
  /** the interrupt's id (a stored card: the approval's id) */
  id: string;
  kind: string;
  runId: string;
  state: "pending" | "approved" | "declined";
  /** what the card says: the action's name, one line, and a few of its parameters (plain text) */
  title?: string;
  summary?: string;
  params?: Record<string, unknown>;
};

/** A file attached to a message, as a message shows it. */
export type AttachmentInfo = {
  kind: "image" | "document";
  id: string;
  name: string;
  /** a picture: where to show it from (a short-lived link, or the picture the person chose) */
  url?: string;
  /** a document: how much of it there is, when known */
  chars?: number;
  pages?: number;
};

export type ChatPart =
  | { type: "text"; text: string }
  /** what a person attached to this message */
  | { type: "attachment"; file: AttachmentInfo }
  /** the model's thinking, shown collapsed under "Thinking" */
  | { type: "reasoning"; text: string }
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
      /** set when the call is an interrupt waiting for an answer */
      approval?: ToolApproval;
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
  | { type: "submitted"; text: string; id: string; files?: AttachmentInfo[] }
  | { type: "event"; event: ParsedEvent }
  | { type: "failed"; message: string; retryable?: boolean; code?: string }
  | { type: "loaded"; conversation: Conversation }
  | { type: "reset" }
  | { type: "stopped" }
  /** the connection came back after a loss: the turn is running again (the same run, picked up where it was) */
  | { type: "resumed" };

/** A stored conversation as the screen shows it: tool calls and their results fold into the
 * assistant message that made them, so a reload looks like the stream did. */
export function fromStored(messages: StoredMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  const results = new Map<string, Extract<StoredPart, { type: "tool_result" }>>();
  const cards = new Map<string, Extract<StoredPart, { type: "interrupt" }>>();
  for (const m of messages) {
    for (const p of m.parts) {
      if (p.type === "tool_result") results.set(p.id, p);
      if (p.type === "interrupt") cards.set(p.tool_call_id, p);
    }
  }
  let current: ChatMessage | null = null;
  for (const m of messages) {
    if (m.role === "user") {
      current = null;
      out.push({
        id: m.id,
        role: "user",
        parts: m.parts.flatMap((p): ChatPart[] =>
          p.type === "text"
            ? [{ type: "text", text: p.text }]
            : p.type === "attachment"
              ? [
                  {
                    type: "attachment",
                    file: { kind: p.kind, id: p.id, name: p.name, url: p.url },
                  },
                ]
              : [],
        ),
      });
    } else if (m.role === "assistant") {
      if (!current) {
        current = { id: m.id, role: "assistant", parts: [] };
        out.push(current);
      }
      for (const p of m.parts) {
        if (p.type === "text" && p.text) current.parts.push({ type: "text", text: p.text });
        if (p.type === "reasoning" && p.text)
          current.parts.push({ type: "reasoning", text: p.text });
        if (p.type === "tool_call") {
          const r = results.get(p.id);
          const card = cards.get(p.id);
          // a call with a card and no result yet is still waiting for the person
          const waiting = !r && card?.status === "pending";
          current.parts.push({
            type: "tool",
            id: p.id,
            name: p.name,
            arguments: p.arguments,
            status: r ? r.status : waiting ? "running" : "error",
            output: r?.output,
            ...(card
              ? {
                  approval: {
                    id: card.approval_id ?? card.tool_call_id,
                    kind: card.kind,
                    runId: card.run_id,
                    state: card.status,
                    title: card.title,
                    summary: card.summary,
                    params: card.params,
                  },
                }
              : {}),
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
          {
            id: action.id,
            role: "user",
            parts: [
              { type: "text", text: action.text },
              ...(action.files ?? []).map((file): ChatPart => ({ type: "attachment", file })),
            ],
          },
          { id: `${action.id}-reply`, role: "assistant", parts: [], streaming: true },
        ],
      };
    case "stopped":
      return { ...state, phase: "idle", messages: settle(state.messages) };
    case "resumed":
      return {
        ...state,
        phase: "working",
        error: null,
        messages: withLast(state.messages, (m) =>
          m.role === "assistant" ? { ...m, streaming: true } : m,
        ),
      };
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
    case "reasoning": {
      const text = String(data.text ?? "");
      return {
        ...base,
        messages: withLast(base.messages, (m) => {
          if (m.role !== "assistant") return m;
          const parts = [...m.parts];
          const tail = parts[parts.length - 1];
          if (tail && tail.type === "reasoning")
            parts[parts.length - 1] = { ...tail, text: tail.text + text };
          else parts.push({ type: "reasoning", text });
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
          // a progress event names its tool call when the engine says which (parallel jobs); else the last running one
          const callId = typeof data.tool_call_id === "string" ? data.tool_call_id : null;
          for (let i = parts.length - 1; i >= 0; i--) {
            const p = parts[i];
            if (p && p.type === "tool" && p.status === "running" && (!callId || p.id === callId)) {
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
