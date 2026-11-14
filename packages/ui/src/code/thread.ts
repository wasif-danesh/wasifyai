// A coding session's stream as what the screen draws: for each turn, the person's request, the agent's steps
// as quiet lines, its words, and how the turn ended. Pure, so it is tested without a screen.
import type { CodeAnswer, CodeAsk, CodeEnding, CodeEvent, CodeTurn } from "@wasifyai/client";

export type Step = {
  id: string;
  tool: string;
  /** what the tool was given, short: a path, a pattern */
  given: Record<string, unknown>;
  /** "refused": the person said no and it did not run */
  status: "started" | "ok" | "error" | "refused";
  /** what it gave back (cut by the engine) */
  text: string;
  /** how its question was answered; "allowed": it ran unasked because its kind is allowed for the project */
  answer?: CodeAnswer | "allowed";
};

export type Part =
  | { kind: "steps"; steps: Step[] }
  | { kind: "message"; text: string; writing: boolean }
  /** the approval card: open while the agent waits; then how it was answered ("": the turn ended first) */
  | { kind: "ask"; id: string; ask: CodeAsk; open: boolean; answer: CodeAnswer | "" }
  | { kind: "refusal"; message: string };

export type TurnView = {
  id: string;
  request: string;
  parts: Part[];
  /** how many tool steps it took, when the steps themselves are not known (a turn from before the app started) */
  steps: number;
  working: boolean;
  ended: CodeEnding;
  /** a sentence for a person: why it ended in an error, what the engine said */
  detail: string;
  /** how many files the turn changed */
  changed: number;
  /** the person undid the turn */
  undone: boolean;
  canUndo: boolean;
  canRedo: boolean;
};

const EDITS = ["create", "str_replace", "insert", "undo_edit"];

/** Whether a step changes a file (or tried to). */
export function isEdit(step: Pick<Step, "tool" | "given">): boolean {
  return step.tool === "file_editor" && EDITS.includes(String(step.given.command ?? ""));
}

/** One line for a step: "Read src/app.py", "Looked for *.py", "Searched for TODO". */
export function stepLine(
  step: Pick<Step, "tool" | "given"> & Partial<Pick<Step, "status">>,
): string {
  const g = step.given;
  const path = typeof g.path === "string" ? shortPath(g.path) : "";
  const pattern = typeof g.pattern === "string" ? g.pattern : "";
  if (step.tool === "glob") return `Looked for files named ${pattern || "anything"}`;
  if (step.tool === "grep") return `Searched for “${pattern}”${path ? ` in ${path}` : ""}`;
  if (step.tool === "planning_file_editor" || step.tool === "file_editor") {
    if (g.command === "view" || !g.command) return `Read ${path || "a file"}`;
    // a session that only reads has no way to change a file: whatever it tried did not happen
    if (step.tool === "planning_file_editor") return `Tried to change ${path}`;
    const made = g.command === "create";
    if (step.status === "ok") return `${made ? "Wrote" : "Changed"} ${path}`;
    if (step.status === "refused") return `Did not change ${path}: you said no`;
    if (step.status === "error") return `Could not change ${path}`;
    return `Wants to ${made ? "write" : "change"} ${path}`;
  }
  return path ? `${step.tool}: ${path}` : step.tool;
}

function shortPath(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts.length <= 3 ? path : `…/${parts.slice(-3).join("/")}`;
}

function fromEvents(turn: TurnView, events: CodeEvent[]): TurnView {
  const parts: Part[] = [];
  const steps = new Map<string, Step>();
  let writing = "";
  let { working, ended, detail, changed } = turn;
  const asks: Extract<Part, { kind: "ask" }>[] = [];
  const flush = () => {
    writing = "";
    const last = parts[parts.length - 1];
    if (last?.kind === "message" && last.writing) parts.pop();
  };
  for (const e of events) {
    if (e.event === "tool_call") {
      flush();
      const step: Step = {
        id: e.id,
        tool: e.name,
        given: e.arguments,
        status: "started",
        text: "",
      };
      steps.set(e.id, step);
      const last = parts[parts.length - 1];
      if (last?.kind === "steps") last.steps.push(step);
      else parts.push({ kind: "steps", steps: [step] });
    } else if (e.event === "tool_result") {
      const step = steps.get(e.id);
      if (step) {
        step.status = e.status;
        step.text = e.output.text ?? "";
        if (e.output.answer) step.answer = e.output.answer;
      }
      // the step a card asked about has its result: the card is answered
      for (const ask of asks) {
        if (ask.open && ask.ask.step_id === e.id) {
          ask.open = false;
          ask.answer = e.output.answer && e.output.answer !== "allowed" ? e.output.answer : "";
        }
      }
    } else if (e.event === "interrupt") {
      flush();
      const ask = {
        kind: "ask" as const,
        id: e.interrupt_id,
        ask: e.payload,
        open: true,
        answer: "" as const,
      };
      asks.push(ask);
      parts.push(ask);
    } else if (e.event === "token") {
      writing += e.text;
      const last = parts[parts.length - 1];
      if (last?.kind === "message" && last.writing) last.text = writing;
      else parts.push({ kind: "message", text: writing, writing: true });
    } else if (e.event === "code_message") {
      flush();
      parts.push({ kind: "message", text: e.text, writing: false });
    } else if (e.event === "code_refusal") {
      flush();
      // the model's own words replace the same words said as its message
      const last = parts[parts.length - 1];
      if (last?.kind === "message" && last.text === e.message) parts.pop();
      parts.push({ kind: "refusal", message: e.message });
    } else if (e.event === "code_state") {
      working = e.state !== "done";
      if (e.state === "turn_ended" || e.state === "done") {
        for (const ask of asks) ask.open = false; // a card nobody answered is closed with the turn
      }
      if (e.state === "done") {
        flush();
        ended = e.why ?? "";
        detail = e.detail ?? "";
        // the turn's row says it too, once it is read again; until then the event does
        if (typeof e.changed === "number" && !changed) changed = e.changed;
      }
    }
  }
  const count = [...steps.values()].length;
  return { ...turn, parts, steps: count || turn.steps, working, ended, detail, changed };
}

/**
 * The session as turns to draw. A turn whose events are known (it ran since the app started) shows its steps;
 * an older one shows what was kept: the request, the answer and how many steps it took.
 */
export function buildThread(turns: CodeTurn[], events: CodeEvent[]): TurnView[] {
  const byTurn = new Map<string, CodeEvent[]>();
  for (const e of events) {
    const list = byTurn.get(e.run_id);
    if (list) list.push(e);
    else byTurn.set(e.run_id, [e]);
  }
  const known = new Set(turns.map((t) => t.id));
  const views = turns.map((t) => {
    const kept: Part[] = [];
    if (t.why === "refused") kept.push({ kind: "refusal", message: t.answer });
    else if (t.answer) kept.push({ kind: "message", text: t.answer, writing: false });
    const view: TurnView = {
      id: t.id,
      request: t.request,
      parts: kept,
      steps: t.steps,
      working: t.state !== "done",
      ended: t.state === "done" ? t.why : "",
      detail: t.notes[t.notes.length - 1] ?? "",
      changed: t.changed ?? 0,
      undone: Boolean(t.undone),
      canUndo: Boolean(t.can_undo),
      canRedo: Boolean(t.can_redo),
    };
    const mine = byTurn.get(t.id);
    return mine ? fromEvents({ ...view, parts: [] }, mine) : view;
  });
  // a turn that has just begun and is not in the list yet
  for (const [id, mine] of byTurn) {
    if (known.has(id)) continue;
    views.push(
      fromEvents(
        {
          id,
          request: "",
          parts: [],
          steps: 0,
          working: true,
          ended: "",
          detail: "",
          changed: 0,
          undone: false,
          canUndo: false,
          canRedo: false,
        },
        mine,
      ),
    );
  }
  return views;
}
