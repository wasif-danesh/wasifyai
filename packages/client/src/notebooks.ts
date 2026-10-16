// Notebooks (ADR-0065): the library routes under `/products/wasifyai-notebooks`, a question as a run of the
// product's graph, and the reducer that folds a turn's events into what the chat pane shows.
import type { ParsedEvent } from "./sse";
import { HttpError, type Transport, errorMessage } from "./transport";

export const NOTEBOOKS_PRODUCT = "wasifyai-notebooks";

export type NotebookSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  opened_at: string | null;
  sources: number;
  ready: number;
  reading: number;
  failed: number;
};

export type SourceStatus = "pending" | "processing" | "ready" | "failed" | "cancelled";

export type NotebookSource = {
  id: string;
  notebook_id: string;
  folder_id: string | null;
  title: string;
  kind: "file" | "note";
  status: SourceStatus;
  error: string | null;
  mime: string | null;
  suffix: string | null;
  size_bytes: number | null;
  pages: number | null;
  created_at: string;
  updated_at: string;
  /** only when one source is read (`get`) */
  content?: string | null;
};

export type NotebookFolder = {
  id: string;
  notebook_id: string;
  parent_id: string | null;
  name: string;
};

export type UploadResult = {
  created: NotebookSource[];
  duplicates: NotebookSource[];
  rejected: { name: string; reason: string }[];
};

/** A passage an answer cites, with its text as it was when the answer was written. */
export type NotebookCitation = {
  n: number;
  chunk_id: number;
  document_id: string;
  title: string;
  start_line: number | null;
  end_line: number | null;
  text: string;
};

export type NotebookMessage = {
  id: string;
  seq: number;
  role: "user" | "assistant";
  text: string;
  citations: NotebookCitation[];
  created_at: string;
};

export type NotebookConversationSummary = {
  id: string;
  notebook_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type NotebookConversation = NotebookConversationSummary & { messages: NotebookMessage[] };

export type SetupProgress = {
  state: "idle" | "installing" | "ready" | "failed";
  step: string | null;
  steps: string[];
  message: string;
  done_bytes: number;
  total_bytes: number;
};

export type ReaderSetup =
  | { available: false; message: string }
  | {
      available: true;
      installed: boolean;
      offer: {
        id: string;
        size_bytes: number;
        licences: string;
        source: string;
        needs_free_bytes: number;
      };
      progress: SetupProgress;
    };

export type NotebooksStatus = {
  embedder: { ready: boolean; id: string; size_bytes: number };
  reader: { ready: boolean; id: string; needed_for: string[]; setup: ReaderSetup };
  index: { chunks: number; embedder: string; dimension: number };
};

const JSON_HEADERS = { "content-type": "application/json" };

export function createNotebooksApi(transport: Transport) {
  const base = `/products/${NOTEBOOKS_PRODUCT}`;
  async function request(path: string, init?: RequestInit): Promise<Response> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    return res;
  }
  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await request(path, init);
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }
  async function none(path: string, init?: RequestInit): Promise<void> {
    const res = await request(path, init);
    if (!res.ok && res.status !== 404) throw new HttpError(res.status, await errorMessage(res));
  }
  const nb = (id: string) => `${base}/notebooks/${encodeURIComponent(id)}`;
  const doc = (id: string, did: string) => `${nb(id)}/documents/${encodeURIComponent(did)}`;
  const send = (method: string, body?: unknown): RequestInit => ({
    method,
    headers: JSON_HEADERS,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  return {
    status: () => json<NotebooksStatus>(`${base}/status`),
    setupReader: (confirmBytes: number) =>
      json<SetupProgress>(`${base}/setup/reader`, send("POST", { confirm_bytes: confirmBytes })),

    list: () => json<NotebookSummary[]>(`${base}/notebooks`),
    create: (title?: string) =>
      json<NotebookSummary>(`${base}/notebooks`, send("POST", title ? { title } : {})),
    get: (id: string) => json<NotebookSummary>(nb(id)),
    rename: (id: string, title: string) => json<NotebookSummary>(nb(id), send("PATCH", { title })),
    remove: (id: string) => none(nb(id), { method: "DELETE" }),

    sources: (id: string) => json<NotebookSource[]>(`${nb(id)}/documents`),
    source: (id: string, did: string) => json<NotebookSource>(doc(id, did)),
    addNote: (id: string, title: string, content: string, folderId?: string | null) =>
      json<NotebookSource>(
        `${nb(id)}/documents`,
        send("POST", { title, content, folder_id: folderId ?? null }),
      ),
    upload(id: string, files: File[], folderId?: string | null) {
      const form = new FormData();
      for (const f of files) form.append("files", f, f.name);
      if (folderId) form.append("folder_id", folderId);
      return json<UploadResult>(`${nb(id)}/documents/upload`, { method: "POST", body: form });
    },
    renameSource: (id: string, did: string, title: string) =>
      json<NotebookSource>(doc(id, did), send("PATCH", { title })),
    editNote: (id: string, did: string, content: string) =>
      json<NotebookSource>(doc(id, did), send("PATCH", { content })),
    removeSource: (id: string, did: string) => none(doc(id, did), { method: "DELETE" }),
    retry: (id: string, did: string) => none(`${doc(id, did)}/retry`, { method: "POST" }),
    cancel: (id: string, did: string) => none(`${doc(id, did)}/cancel`, { method: "POST" }),
    move: (id: string, ids: string[], folderId: string | null) =>
      json<{ moved: number }>(
        `${nb(id)}/documents/move`,
        send("POST", { document_ids: ids, folder_id: folderId }),
      ),
    /** The stored file, as a blob (the token rides on the request, so a plain link would not do). */
    async original(id: string, did: string): Promise<Blob> {
      const res = await request(`${doc(id, did)}/original`);
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
      return res.blob();
    },

    folders: (id: string) => json<NotebookFolder[]>(`${nb(id)}/folders`),
    createFolder: (id: string, name: string, parentId?: string | null) =>
      json<NotebookFolder>(
        `${nb(id)}/folders`,
        send("POST", { name, parent_id: parentId ?? null }),
      ),
    renameFolder: (id: string, fid: string, name: string) =>
      none(`${nb(id)}/folders/${encodeURIComponent(fid)}`, send("PATCH", { name })),
    removeFolder: (id: string, fid: string) =>
      none(`${nb(id)}/folders/${encodeURIComponent(fid)}`, { method: "DELETE" }),

    conversations: (id: string) => json<NotebookConversationSummary[]>(`${nb(id)}/conversations`),
    conversation: (id: string, cid: string) =>
      json<NotebookConversation>(`${nb(id)}/conversations/${encodeURIComponent(cid)}`),
    renameConversation: (id: string, cid: string, title: string) =>
      none(`${nb(id)}/conversations/${encodeURIComponent(cid)}`, send("PATCH", { title })),
    removeConversation: (id: string, cid: string) =>
      none(`${nb(id)}/conversations/${encodeURIComponent(cid)}`, { method: "DELETE" }),

    /** Notebooks found by their title and the names of their sources (My creations search). */
    async find(query: string): Promise<string[]> {
      const params = new URLSearchParams({ q: query, kind: "notebook", limit: "30" });
      const res = await json<{ results: { id: string; product_id: string }[] }>(
        `/creations/search?${params}`,
      );
      return res.results.filter((r) => r.product_id === NOTEBOOKS_PRODUCT).map((r) => r.id);
    },
  };
}

export type NotebooksApi = ReturnType<typeof createNotebooksApi>;

// ---- a question and its answer ---------------------------------------------------------------

/** Words a person reads for a refusal code the graph can answer with (the graph's own sentence wins). */
export type AskedMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations: NotebookCitation[];
  /** the answer is still arriving */
  streaming?: boolean;
  /** what was searched: shown as one line above the answer */
  searched?: { sources: number; passages: number };
};

export type AskError = { code: string; message: string; retryable: boolean };

export type AskState = {
  conversationId: string | null;
  title: string;
  messages: AskedMessage[];
  phase: "idle" | "searching" | "answering" | "error";
  error: AskError | null;
  runId: string | null;
  lastSeq: number;
};

export const initialAsk: AskState = {
  conversationId: null,
  title: "",
  messages: [],
  phase: "idle",
  error: null,
  runId: null,
  lastSeq: 0,
};

export type AskAction =
  | { type: "submitted"; text: string; id: string }
  | { type: "event"; event: ParsedEvent }
  | { type: "failed"; message: string; retryable?: boolean; code?: string }
  | { type: "loaded"; conversation: NotebookConversation }
  | { type: "reset" }
  | { type: "stopped" };

export function isWorking(state: AskState): boolean {
  return state.phase === "searching" || state.phase === "answering";
}

function settle(messages: AskedMessage[]): AskedMessage[] {
  return messages.map((m) => (m.streaming ? { ...m, streaming: false } : m));
}

function withLast(messages: AskedMessage[], fn: (m: AskedMessage) => AskedMessage): AskedMessage[] {
  const i = messages.length - 1;
  const last = messages[i];
  if (!last) return messages;
  return [...messages.slice(0, i), fn(last)];
}

function dropEmptyReply(messages: AskedMessage[]): AskedMessage[] {
  return settle(messages.filter((m) => !(m.role === "assistant" && m.streaming && !m.text)));
}

export function askReducer(state: AskState, action: AskAction): AskState {
  switch (action.type) {
    case "reset":
      return initialAsk;
    case "loaded":
      return {
        ...initialAsk,
        conversationId: action.conversation.id,
        title: action.conversation.title,
        messages: action.conversation.messages.map((m) => ({
          id: m.id,
          role: m.role,
          text: m.text,
          citations: m.citations,
        })),
      };
    case "submitted":
      return {
        ...state,
        phase: "searching",
        error: null,
        runId: null,
        lastSeq: 0,
        messages: [
          ...state.messages,
          { id: action.id, role: "user", text: action.text, citations: [] },
          { id: `${action.id}-reply`, role: "assistant", text: "", citations: [], streaming: true },
        ],
      };
    case "stopped":
      return { ...state, phase: "idle", messages: dropEmptyReply(state.messages) };
    case "failed":
      return {
        ...state,
        phase: "error",
        messages: dropEmptyReply(state.messages),
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

function onEvent(state: AskState, e: ParsedEvent): AskState {
  const data = e.data as unknown as Record<string, unknown>;
  const seq = typeof data.seq === "number" ? data.seq : state.lastSeq;
  const base: AskState = {
    ...state,
    runId: typeof data.run_id === "string" ? data.run_id : state.runId,
    lastSeq: Math.max(state.lastSeq, seq),
  };
  switch (e.event) {
    case "tool_call": {
      if (data.name !== "search_sources") return base;
      const args = (data.arguments as Record<string, unknown>) ?? {};
      const sources = typeof args.sources === "number" ? args.sources : 0;
      return {
        ...base,
        messages: withLast(base.messages, (m) => ({ ...m, searched: { sources, passages: 0 } })),
      };
    }
    case "tool_result": {
      if (data.name !== "search_sources") return base;
      const out = (data.output as { hits?: unknown[] }) ?? {};
      const passages = Array.isArray(out.hits) ? out.hits.length : 0;
      return {
        ...base,
        phase: "answering",
        messages: withLast(base.messages, (m) => ({
          ...m,
          searched: { sources: m.searched?.sources ?? 0, passages },
        })),
      };
    }
    case "token":
      return {
        ...base,
        phase: "answering",
        messages: withLast(base.messages, (m) =>
          m.role === "assistant" ? { ...m, text: m.text + String(data.text ?? "") } : m,
        ),
      };
    case "done": {
      const out = (data.outputs as Record<string, unknown>) ?? {};
      if (out.status === "refused") {
        const refusal = (out.refusal as Record<string, string>) ?? {};
        return {
          ...base,
          phase: "error",
          messages: dropEmptyReply(base.messages),
          error: {
            code: refusal.code ?? "refused",
            message: refusal.message ?? "That could not be sent.",
            retryable: false,
          },
        };
      }
      const reply = typeof out.reply === "string" ? out.reply : null;
      const citations = Array.isArray(out.citations) ? (out.citations as NotebookCitation[]) : [];
      return {
        ...base,
        phase: "idle",
        conversationId:
          typeof out.conversation_id === "string" ? out.conversation_id : base.conversationId,
        title: typeof out.title === "string" && out.title ? out.title : base.title,
        // the checked answer replaces what streamed: its labels have been verified
        messages: settle(
          withLast(base.messages, (m) =>
            m.role === "assistant" ? { ...m, text: reply ?? m.text, citations } : m,
          ),
        ),
      };
    }
    case "error":
      return {
        ...base,
        phase: "error",
        messages: dropEmptyReply(base.messages),
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
