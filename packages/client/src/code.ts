// Coding sessions (ADR-0101): a project's folder, a session on it, and the session's stream. The window calls
// the coding product's routes and never the coding engine. A session only reads ("Plan"), or changes files
// ("Ask me", "Work on its own"); it never runs a command at this stage.
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

/** How much the agent may do: read only; change files and ask first where a rule says; change files unasked. */
export type CodeMode = "plan" | "ask" | "own";

/** A kind of request the agent asks about, and a person can allow for one project. */
export type CodeAskKind = "not_undoable" | "delete" | "install";

/** A person's answer to an approval card. "allow" is yes, and that kind is not asked again in this project. */
export type CodeAnswer = "yes" | "allow" | "no";

export type CodeSession = {
  id: string;
  title: string;
  /** the folder's whole path */
  folder: string;
  /** the folder's name */
  project: string;
  mode: CodeMode;
  model: string;
  state: "new" | "working" | "turn_ended" | "checking" | "done";
  working: boolean;
  /** the agent waits for the person's yes or no */
  waiting: boolean;
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
  /** how many files the turn changed */
  changed: number;
  /** the person undid the turn */
  undone: boolean;
  /** it is the turn "Undo this turn" would undo now, or "Bring it back" would bring back */
  can_undo: boolean;
  can_redo: boolean;
};

/** What the approval card shows (the stream's `interrupt` of kind `code_ask`). */
export type CodeAsk = {
  ask: CodeAskKind;
  /** the step that waits */
  step_id: string;
  tool: string;
  command: string;
  /** from the project's top */
  path: string;
  /** the agent's reason, when it gave one */
  says: string;
  project: string;
  /** whether Undo covers it */
  undo: boolean;
  steps: number;
};

/** One file a turn changed. */
export type CodeChangedFile = {
  path: string;
  what: "added" | "changed" | "deleted";
  /** it is a test file */
  test: boolean;
};

/** A turn that changed files (the Changes tab). */
export type CodeChange = {
  turn_id: string;
  position: number;
  request: string;
  started_at: string;
  undone: boolean;
  can_undo: boolean;
  can_redo: boolean;
  files: CodeChangedFile[];
};

/** One changed file, before and after. A side that does not exist is null. */
export type CodeChangeFile = CodeChangedFile & {
  binary: boolean;
  too_large: boolean;
  before: string | null;
  after: string | null;
  /** the two as lines: `a` and `b` are the line numbers before and after */
  lines: { t: "same" | "add" | "del"; text: string; a?: number; b?: number }[];
};

/** What an undo or a "bring it back" did. */
export type CodeUndone = {
  turn_id: string;
  undone: boolean;
  files: number;
  /** files the person changed themselves since the turn went with it */
  own_changes: boolean;
  notes: string[];
};

/** What a project may do: each kind of request, and whether the person allowed it. */
export type CodeProject = {
  project: string;
  folder: string;
  mode: CodeMode;
  kinds: { id: CodeAskKind; allowed: boolean; asked_now: boolean }[];
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
      /** with "done", in a session that may change files: how many files the turn changed */
      changed?: number;
    }
  | { event: "interrupt"; interrupt_id: string; kind: "code_ask"; payload: CodeAsk }
  | { event: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | {
      event: "tool_result";
      id: string;
      name: string;
      status: "ok" | "error" | "refused";
      /** `answer`: how the step's question was answered ("allowed": its kind is allowed for the project) */
      output: { text?: string; answer?: CodeAnswer | "allowed" };
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
    start(input: {
      folder: string;
      title?: string;
      model?: string;
      mode?: CodeMode;
    }): Promise<CodeSession> {
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
    /** How much the agent asks, from now on. */
    setMode(id: string, mode: CodeMode): Promise<CodeSession> {
      return json<CodeSession>(`${BASE}/sessions/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ mode }),
      });
    },
    /** Answer an approval card. False when nothing waits under that id any more. */
    async answer(id: string, askId: string, answer: CodeAnswer): Promise<boolean> {
      const out = await json<{ answered: boolean }>(
        `${BASE}/sessions/${encodeURIComponent(id)}/asks/${encodeURIComponent(askId)}`,
        post({ answer }),
      );
      return out.answered;
    },
    /** The turns that changed files, the newest first. */
    async changes(id: string): Promise<CodeChange[]> {
      return (
        await json<{ items: CodeChange[] }>(`${BASE}/sessions/${encodeURIComponent(id)}/changes`)
      ).items;
    },
    /** One file a turn changed, before and after. */
    change(id: string, turnId: string, path: string): Promise<CodeChangeFile> {
      const q = new URLSearchParams({ path });
      return json<CodeChangeFile>(
        `${BASE}/sessions/${encodeURIComponent(id)}/changes/${encodeURIComponent(turnId)}/file?${q}`,
      );
    },
    /** Put the project's files back to how they were before the turn. */
    undo(id: string, turnId: string): Promise<CodeUndone> {
      return json<CodeUndone>(
        `${BASE}/sessions/${encodeURIComponent(id)}/turns/${encodeURIComponent(turnId)}/undo`,
        post(),
      );
    },
    /** Bring an undone turn's changes back. */
    redo(id: string, turnId: string): Promise<CodeUndone> {
      return json<CodeUndone>(
        `${BASE}/sessions/${encodeURIComponent(id)}/turns/${encodeURIComponent(turnId)}/redo`,
        post(),
      );
    },
    /** What this session's project may do. */
    project(id: string): Promise<CodeProject> {
      return json<CodeProject>(`${BASE}/sessions/${encodeURIComponent(id)}/project`);
    },
    /** Allow a kind of request for the project, or take that back. */
    allow(id: string, kind: CodeAskKind, allowed: boolean): Promise<CodeProject> {
      return json<CodeProject>(
        `${BASE}/sessions/${encodeURIComponent(id)}/project/allowed/${encodeURIComponent(kind)}`,
        {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ allowed }),
        },
      );
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
