// Coding sessions (ADR-0101): a project's folder, a session on it, and the session's stream. The window calls
// the coding product's routes and never the coding engine. In this stage every session only reads ("Plan").
import { parseSse } from "./sse";
import { HttpError, type Transport, errorMessage } from "./transport";

export const CODE_PRODUCT_ID = "wasifyai-code";
const BASE = `/products/${CODE_PRODUCT_ID}/code`;

export type CodeModel = {
  id: string;
  title: string;
  /** "cloud": what the agent reads is sent to the model's provider; "this-computer": nothing leaves */
  where: "cloud" | "this-computer";
  default: boolean;
  /** false: its key is not saved, or its address is not set */
  ready: boolean;
};

/** How a turn ended. A refusal is the model's own answer, not an error. */
export type CodeEnding = "finished" | "stopped" | "step_limit" | "error" | "refused" | "";

export type CodeSession = {
  id: string;
  title: string;
  /** the folder's whole path */
  folder: string;
  /** the folder's name */
  project: string;
  mode: "plan";
  model: string;
  state: "new" | "working" | "turn_ended" | "checking" | "done";
  working: boolean;
  /** the check's word; empty when nothing was ever checked */
  result: "" | "passed" | "failed" | "not_checked" | "could_not_check";
  turns: number;
  answer: string;
  ended: CodeEnding;
  cost_usd: number;
  /** the most this session may cost */
  cost_limit_usd: number;
  model_calls: number;
  tokens_in: number;
  tokens_out: number;
  created_at: string;
  updated_at: string;
};

export type CodeTurn = {
  id: string;
  position: number;
  request: string;
  state: CodeSession["state"];
  result: CodeSession["result"];
  why: CodeEnding;
  answer: string;
  steps: number;
  notes: string[];
  started_at: string;
  finished_at: string | null;
};

/** One event of a session's stream (docs/contracts/sse-events.md, "A coding session's stream"). */
export type CodeEvent = { seq: number; run_id: string; thread_id: string; ts: string } & (
  | {
      event: "code_state";
      state: "working" | "turn_ended" | "checking" | "done";
      why?: CodeEnding;
      result?: CodeSession["result"];
      detail?: string;
      cost_usd: number;
    }
  | { event: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | {
      event: "tool_result";
      id: string;
      name: string;
      status: "ok" | "error";
      output: { text?: string };
    }
  | { event: "token" | "reasoning"; node: string; text: string }
  | { event: "code_message"; text: string }
  | { event: "code_refusal"; message: string; category?: string }
);

/** One entry of a project's folder (the Files tab). `path` is from the project's top. */
export type CodeEntry = { name: string; path: string; kind: "file" | "folder"; bytes: number };

/** One file of the project, to read. A file that is not text has `binary` and no text. */
export type CodeFile = {
  path: string;
  bytes: number;
  binary: boolean;
  text: string;
  lines: number;
  /** the file is longer than what is shown */
  cut: boolean;
};

/** The coding engine as an optional part: is it set up, can this computer run it. */
export type CodeEngine = { supported: boolean; installed: boolean; running: boolean };

export type CodeApi = ReturnType<typeof createCodeApi>;

export function createCodeApi(transport: Transport) {
  async function call(path: string, init?: RequestInit): Promise<Response> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return res;
  }
  const json = async <T>(path: string, init?: RequestInit) =>
    (await (await call(path, init)).json()) as T;
  const post = (body?: unknown): RequestInit => ({
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  return {
    /** Whether the coding engine is set up on this computer (desktop only; elsewhere: not supported). */
    async engine(): Promise<CodeEngine> {
      const res = await transport.fetch("/desktop/coding-engine");
      if (!res.ok) return { supported: false, installed: false, running: false };
      return (await res.json()) as CodeEngine;
    },
    async models(): Promise<CodeModel[]> {
      return (await json<{ items: CodeModel[] }>(`${BASE}/models`)).items;
    },
    async sessions(): Promise<CodeSession[]> {
      return (await json<{ items: CodeSession[] }>(`${BASE}/sessions?limit=200`)).items;
    },
    session(id: string): Promise<CodeSession> {
      return json<CodeSession>(`${BASE}/sessions/${encodeURIComponent(id)}`);
    },
    async turns(id: string): Promise<CodeTurn[]> {
      return (await json<{ items: CodeTurn[] }>(`${BASE}/sessions/${encodeURIComponent(id)}/turns`))
        .items;
    },
    /** A new session on a folder. Nothing is read and nothing runs until a message is sent. */
    start(input: { folder: string; title?: string; model?: string }): Promise<CodeSession> {
      return json<CodeSession>(`${BASE}/sessions`, post(input));
    },
    /** Begin a turn. It answers at once; the agent's work arrives on the stream. */
    async send(id: string, text: string): Promise<CodeSession> {
      const out = await json<{ session: CodeSession }>(
        `${BASE}/sessions/${encodeURIComponent(id)}/messages`,
        post({ text }),
      );
      return out.session;
    },
    /** Stop the turn in flight. It answers when the turn is closed. */
    async stop(id: string): Promise<CodeSession> {
      const out = await json<{ session: CodeSession }>(
        `${BASE}/sessions/${encodeURIComponent(id)}/stop`,
        post(),
      );
      return out.session;
    },
    /** One folder of the session's project; `path` is from the project's top ("" is the top). */
    async files(id: string, path = ""): Promise<CodeEntry[]> {
      const q = new URLSearchParams({ path });
      const out = await json<{ entries: CodeEntry[] }>(
        `${BASE}/sessions/${encodeURIComponent(id)}/files?${q}`,
      );
      return out.entries;
    },
    /** The project's files whose name holds `query`. */
    async find(id: string, query: string): Promise<{ entries: CodeEntry[]; more: boolean }> {
      const q = new URLSearchParams({ q: query });
      return json(`${BASE}/sessions/${encodeURIComponent(id)}/files/find?${q}`);
    },
    /** Change the most this session may cost. */
    setLimit(id: string, usd: number): Promise<CodeSession> {
      return json<CodeSession>(`${BASE}/sessions/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ cost_limit_usd: usd }),
      });
    },
    /** One file of the session's project, to read. */
    file(id: string, path: string): Promise<CodeFile> {
      const q = new URLSearchParams({ path });
      return json<CodeFile>(`${BASE}/sessions/${encodeURIComponent(id)}/file?${q}`);
    },
    async remove(id: string): Promise<void> {
      await call(`${BASE}/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
    },
    /**
     * The session's events as they happen, for as long as the caller reads. `after` is the number of the
     * last event the caller has: the kept ones after it come first. Words as they are written (`token`) are
     * not kept; the finished message (`code_message`) is.
     */
    async *events(id: string, after = 0, signal?: AbortSignal): AsyncGenerator<CodeEvent> {
      const res = await call(`${BASE}/sessions/${encodeURIComponent(id)}/events`, {
        headers: after > 0 ? { "last-event-id": String(after) } : undefined,
        signal,
      });
      if (!res.body) return;
      for await (const parsed of parseSse(res.body)) yield parsed.data as unknown as CodeEvent;
    },
  };
}
