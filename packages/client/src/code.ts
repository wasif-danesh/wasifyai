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
export type CodeAskKind = "not_undoable" | "delete" | "install" | "make";

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
  /** the project's check is running now */
  checking?: boolean;
  /** the last turn stopped and a person must decide (the check still fails, or could not run) */
  needs_you?: boolean;
  /** the project's check command; empty when it has none */
  check_command?: string;
  /** the command that starts the project for its preview; empty when none is set */
  preview_command?: string;
  /** the project's preview is starting or running */
  previewing?: boolean;
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
  /** why the check has its result when the agent itself finished: no_change, no_command, rounds_used, ... */
  check_why?: string;
  /** how many times the check ran in this turn */
  rounds?: number;
  needs_you?: boolean | number;
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

/** One run of the project's check. `round` is 0 for a check the person ran by hand. */
export type CodeCheck = {
  id: string;
  turn_id: string | null;
  round: number;
  command: string;
  result: "passed" | "failed" | "not_checked" | "could_not_check";
  /** for could_not_check and not_checked: missing_command, time_limit, crashed, could_not_start, stopped */
  why: string;
  exit_code: number | null;
  seconds: number;
  /** test files the agent changed or deleted in the turn */
  changed_tests: string[];
  created_at?: string;
};

/** The project's check: its command, what the project's files suggest, and this session's last checks. */
export type CodeCheckInfo = {
  project: string;
  command: string;
  /** "suggested" or "person"; empty when there is no check */
  source: string;
  limit_s: number;
  rounds: number;
  suggested: { command: string; why: string }[];
  result: CodeSession["result"];
  running: boolean;
  checks: CodeCheck[];
};

/** A running (or ended) preview of the project. */
export type CodePreviewRun = {
  state: "starting" | "running" | "ended";
  command: string;
  /** the port it listens on, on this computer; null until it does */
  port: number | null;
  url: string;
  /** it listens on every address: other computers on the same network could reach it */
  open_to_network: boolean;
  /** it has run for a while and listens on no port */
  listens_nowhere: boolean;
  exit_code: number | null;
  /** the person stopped it */
  stopped: boolean;
  /** the end of what it printed */
  output: string;
};

/** The project's preview: its command, what the project's files suggest, and the running one. */
export type CodePreview = {
  project: string;
  command: string;
  suggested: { command: string; why: string }[];
  running: CodePreviewRun | null;
};

/** A project: a folder the person opened for the agent. */
export type CodeWorkspace = { id: string; name: string; folder: string };

/** A skill that can be switched on for a project (ADR-0104). */
export type CodeExtension = {
  /** "own:<name>", "catalogue:<name>" or "added:<id>" */
  id: string;
  kind: "skill";
  /** Wasify AI's own, the pinned OpenHands catalogue, or a folder the person added */
  source: "own" | "catalogue" | "added";
  name: string;
  title: string;
  description: string;
  /** words in a message that make the agent use it; empty: the agent reads it when it fits */
  triggers: string[];
  /** what it says it needs, when it says so */
  needs: string;
  default_on: boolean;
  /** on for the project that was asked about; null when none was */
  on: boolean | null;
  /** when the person added it; empty for one of the short list */
  added_at?: string;
};

/** One extension with the whole text it gives the agent, and where it is on. */
export type CodeExtensionDetail = Omit<CodeExtension, "on"> & {
  text: string;
  lines: number;
  licence: string;
  files: number;
  where: (CodeWorkspace & { on: boolean })[];
};

/** What a folder the person chose holds, before it is added. */
export type CodeFolderLook = Omit<CodeExtension, "on"> & {
  text: string;
  lines: number;
  folder: string;
  bytes: number;
  brings: "text";
};

/** Something a new project can be started from. */
export type CodeStarter = { id: string; title: string; says: string; needs: string[] };

/** A terminal of the person's own in the project. */
export type CodeTerminal = {
  id: string;
  folder: string;
  ended: boolean;
  exit_code: number | null;
};

/** What a terminal's stream sends: bytes it printed (base64), or its end. */
export type CodeTerminalEvent =
  | { seq: number; data: string }
  | { seq: number; exit_code: number | null; data?: undefined };

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
      /** how many times the check has run in this turn; with "checking", the round that begins */
      round?: number;
      needs_you?: boolean;
      check_why?: string;
    }
  | ({ event: "code_check"; rounds: number; tail: string } & CodeCheck)
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
  /** the person's message switched skills on: their names, and what a person calls them */
  | { event: "code_skills"; names: string[]; titles: string[] }
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
    /** The project's check. */
    check(id: string): Promise<CodeCheckInfo> {
      return json<CodeCheckInfo>(`${BASE}/sessions/${encodeURIComponent(id)}/check`);
    },
    /** Set the project's check command; an empty one means the project has no check. */
    setCheck(id: string, command: string, limitS?: number): Promise<CodeCheckInfo> {
      return json<CodeCheckInfo>(`${BASE}/sessions/${encodeURIComponent(id)}/check`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(limitS ? { command, limit_s: limitS } : { command }),
      });
    },
    /** Run the check now, outside a turn. It answers when the check has ended. */
    runCheck(id: string): Promise<{ check: CodeCheck; session: CodeSession }> {
      return json(`${BASE}/sessions/${encodeURIComponent(id)}/check/run`, post());
    },
    /** One check with its whole output. */
    checkOutput(
      id: string,
      checkId: string,
    ): Promise<CodeCheck & { output: string; cut: boolean }> {
      return json(
        `${BASE}/sessions/${encodeURIComponent(id)}/checks/${encodeURIComponent(checkId)}`,
      );
    },
    /** Three more rounds: a new turn that tells the agent the check still fails. */
    async tryAgain(id: string): Promise<CodeSession> {
      const out = await json<{ session: CodeSession }>(
        `${BASE}/sessions/${encodeURIComponent(id)}/check/again`,
        post(),
      );
      return out.session;
    },
    /** The person's projects, the newest first. */
    async workspaces(): Promise<CodeWorkspace[]> {
      return (await json<{ items: CodeWorkspace[] }>(`${BASE}/workspaces`)).items;
    },
    /** The short list and what the person added; with a project, whether each is on for it. */
    async extensions(workspaceId = ""): Promise<CodeExtension[]> {
      const q = new URLSearchParams(workspaceId ? { workspace_id: workspaceId } : {});
      return (await json<{ items: CodeExtension[] }>(`${BASE}/extensions?${q}`)).items;
    },
    /** One extension with its whole text. */
    extension(id: string): Promise<CodeExtensionDetail> {
      return json<CodeExtensionDetail>(`${BASE}/extensions/${encodeURIComponent(id)}`);
    },
    /** Switch an extension on or off for one project. */
    switchExtension(id: string, workspaceId: string, on: boolean): Promise<CodeExtension> {
      return json<CodeExtension>(`${BASE}/extensions/${encodeURIComponent(id)}/on`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ workspace_id: workspaceId, on }),
      });
    },
    /** What a folder holds, before it is added. */
    lookAtFolder(folder: string): Promise<CodeFolderLook> {
      return json<CodeFolderLook>(`${BASE}/extensions/look`, post({ folder }));
    },
    /** Copy a skill's folder in; with a project it is switched on for it. */
    addExtension(folder: string, workspaceId = ""): Promise<CodeExtension> {
      return json<CodeExtension>(`${BASE}/extensions`, post({ folder, workspace_id: workspaceId }));
    },
    /** Forget an extension the person added. */
    async removeExtension(id: string): Promise<void> {
      await call(`${BASE}/extensions/${encodeURIComponent(id)}`, { method: "DELETE" });
    },
    /** The project's preview. */
    preview(id: string): Promise<CodePreview> {
      return json<CodePreview>(`${BASE}/sessions/${encodeURIComponent(id)}/preview`);
    },
    /** Start the project inside its protected area; `command` is kept as the project's when given. */
    startPreview(id: string, command?: string): Promise<CodePreview> {
      return json<CodePreview>(
        `${BASE}/sessions/${encodeURIComponent(id)}/preview/start`,
        post(command ? { command } : undefined),
      );
    },
    /** Stop the preview and everything it started. */
    stopPreview(id: string): Promise<CodePreview> {
      return json<CodePreview>(`${BASE}/sessions/${encodeURIComponent(id)}/preview/stop`, post());
    },
    /** What a new project can be started from. */
    async starters(): Promise<CodeStarter[]> {
      return (await json<{ items: CodeStarter[] }>(`${BASE}/starters`)).items;
    },
    /** A new project from a starter, in a new folder inside `parent`, and a session on it. */
    newProject(input: {
      parent: string;
      name: string;
      starter?: string;
      model?: string;
    }): Promise<CodeSession> {
      return json<CodeSession>(`${BASE}/projects`, post(input));
    },
    async terminals(id: string): Promise<CodeTerminal[]> {
      return (
        await json<{ items: CodeTerminal[] }>(
          `${BASE}/sessions/${encodeURIComponent(id)}/terminals`,
        )
      ).items;
    },
    /** Open a terminal of the person's own in the project, inside the sandbox. */
    openTerminal(id: string, cols: number, rows: number): Promise<CodeTerminal> {
      return json<CodeTerminal>(
        `${BASE}/sessions/${encodeURIComponent(id)}/terminals`,
        post({ cols, rows }),
      );
    },
    /** What the person typed. */
    async terminalInput(id: string, terminalId: string, data: string): Promise<void> {
      await call(
        `${BASE}/sessions/${encodeURIComponent(id)}/terminals/${encodeURIComponent(terminalId)}/input`,
        post({ data }),
      );
    },
    async terminalSize(id: string, terminalId: string, cols: number, rows: number): Promise<void> {
      await call(
        `${BASE}/sessions/${encodeURIComponent(id)}/terminals/${encodeURIComponent(terminalId)}/size`,
        post({ cols, rows }),
      );
    },
    async closeTerminal(id: string, terminalId: string): Promise<void> {
      await call(
        `${BASE}/sessions/${encodeURIComponent(id)}/terminals/${encodeURIComponent(terminalId)}`,
        { method: "DELETE" },
      );
    },
    /** What a terminal prints, as it comes; `after` is the number of the last event the caller has. */
    async *terminalEvents(
      id: string,
      terminalId: string,
      after = 0,
      signal?: AbortSignal,
    ): AsyncGenerator<CodeTerminalEvent> {
      const res = await call(
        `${BASE}/sessions/${encodeURIComponent(id)}/terminals/${encodeURIComponent(terminalId)}/events`,
        { headers: after > 0 ? { "last-event-id": String(after) } : undefined, signal },
      );
      if (!res.body) return;
      for await (const parsed of parseSse(res.body)) {
        yield parsed.data as unknown as CodeTerminalEvent;
      }
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
