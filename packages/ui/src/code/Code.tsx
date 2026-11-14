"use client";
// Code (ADR-0101; mockups in docs/spikes/coding-mockups.html): where coding lives, the projects, and a
// session. In Plan the agent reads the project and answers or gives a plan. In "Ask me" and "Work on its
// own" it also changes files, asks first where a rule says so, and every turn can be undone in the Changes
// tab. It also runs commands inside the project's protected area; after a turn that changed files the app runs
// the project's check and sends a failure back to it. The person has a terminal of their own in the Terminal
// tab. The window calls the coding product's routes and never the coding engine.
import type { CodeAnswer, CodeApi, CodeMode, CodeModel, CodeSession } from "@wasifyai/client";
import {
  ArrowUp,
  Check,
  ChevronRight,
  CircleDashed,
  FileDiff,
  Folder,
  FolderOpen,
  Hand,
  ListChecks,
  Lock,
  Plus,
  Redo2,
  Square,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Markdown } from "../chat/thread/markdown/Markdown";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { ConfirmDialog } from "../components/dialog";
import { EmptyState } from "../components/empty-state";
import { Notice } from "../components/notice";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { PageHeader } from "../window-bar";
import { AskCard, MODES, MayDialog, ModePill } from "./Asking";
import { Changes } from "./Changes";
import { CheckCard, CheckDialog, CheckWord, WORDS } from "./Checks";
import { Files } from "./Files";
import { TerminalPane } from "./Terminal";
import {
  type CheckPart,
  type Step,
  type TurnView,
  buildThread,
  isCommand,
  isEdit,
  stepLine,
} from "./thread";
import { useCode } from "./use-code";

export type CodeProps = {
  api: CodeApi;
  /** The computer's own folder window; the chosen folder's whole path, or null when it was closed. */
  pickFolder: () => Promise<string | null>;
  /** Where the coding engine is set up (Settings, Optional parts). */
  onOpenSetup: () => void;
  /** Where a key is saved (Settings, Your keys). */
  onOpenKeys: () => void;
  /**
   * The session the address names (null: the projects). With it the app owns which session is open, so a
   * session has an address of its own and Back leaves it; without it the screen keeps that to itself.
   */
  openId?: string | null;
  onOpenChange?: (id: string | null) => void;
};

const STARTERS = [
  "Explain this project in plain words",
  "Analyse this codebase",
  "How would you add a page? Give me a plan",
];
/** What "Carry out this plan" sends, after the session has left Plan (the agent is given the plan again). */
export const CARRY_OUT = "Carry out this plan.";

const dollars = (n: number) => `$${n.toFixed(2)}`;

export function Code({
  api,
  pickFolder,
  onOpenSetup,
  onOpenKeys,
  openId,
  onOpenChange,
}: CodeProps) {
  const code = useCode(api);
  const { state } = code;
  const shownId = state.session?.id ?? null;
  // the address says which session is open: follow it when it changes
  // biome-ignore lint/correctness/useExhaustiveDependencies: only a change of the address opens or closes
  useEffect(() => {
    if (openId === undefined || openId === shownId) return;
    if (openId) void code.open(openId);
    else code.close();
  }, [openId]);
  const show = (id: string | null) => {
    if (onOpenChange) onOpenChange(id);
    else if (id) void code.open(id);
    else code.close();
  };
  const begin = async (folder: string, model?: string) => {
    const made = await code.start(folder, model);
    if (made) onOpenChange?.(made.id);
  };
  const [model, setModel] = useState<string>("");
  const ready = state.models.filter((m) => m.ready);
  const chosen = ready.find((m) => m.id === model) ?? ready.find((m) => m.default) ?? ready[0];

  const choose = async () => {
    const folder = await pickFolder();
    if (folder) await begin(folder, chosen?.id);
  };

  if (state.loading) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner />
      </div>
    );
  }
  if (state.session) {
    return (
      <Session
        api={api}
        session={state.session}
        models={state.models}
        thread={buildThread(state.turns, state.events, state.checks)}
        busy={state.busy}
        error={state.error}
        onDismiss={code.dismiss}
        onSend={code.send}
        onStop={code.stop}
        onBack={() => show(null)}
        onSetLimit={code.setLimit}
        onSetMode={code.setMode}
        onAnswer={code.answer}
        onUndo={code.undo}
        onRedo={code.redo}
        onRunCheck={code.runCheck}
        onTryAgain={code.tryAgain}
        onReload={code.reload}
        filesTick={state.filesTick}
        undoNote={state.undoNote}
      />
    );
  }
  const engine = state.engine;
  if (engine && !engine.supported) {
    return (
      <Page title="Code">
        <Notice title="Coding is not available on this computer yet">
          The coding engine runs on Apple-silicon Macs for now.
        </Notice>
      </Page>
    );
  }
  if (engine && !engine.installed) {
    return (
      <Page title="Build and fix code by asking">
        <EmptyState
          icon={FolderOpen}
          title="Set up the coding engine first"
          text="Coding uses an optional part of Wasify AI, the coding engine (OpenHands' Agent Server). It takes about 375 MB and runs only on this computer, inside a sandbox."
          action={<Button onClick={onOpenSetup}>Open Optional parts</Button>}
        />
      </Page>
    );
  }
  return (
    <Page
      title={state.sessions.length ? "Projects" : "Build and fix code by asking"}
      lead={
        state.sessions.length
          ? "The folders the agent works in, each with its sessions."
          : "Choose the folder of a project. An agent reads it, answers your questions about it, and changes its files when you ask. Every change can be undone."
      }
      action={
        state.sessions.length ? (
          <Button onClick={choose} disabled={!chosen}>
            <FolderOpen /> Choose a folder
          </Button>
        ) : null
      }
    >
      {state.error ? (
        <Notice tone="error" title="That did not work">
          {state.error}
        </Notice>
      ) : null}
      {ready.length === 0 ? (
        <Notice
          tone="warn"
          title="No model is ready for coding"
          actions={
            <Button size="sm" variant="outline" onClick={onOpenKeys}>
              Open Your keys
            </Button>
          }
        >
          Coding works with Claude Sonnet 5.5 and your own Anthropic key. Save a key for Chat and
          writing, then come back.
        </Notice>
      ) : null}
      {state.sessions.length === 0 ? (
        <div className="grid gap-3 rounded-lg border bg-surface p-5">
          <div className="flex flex-wrap items-center gap-2.5">
            <Button onClick={choose} disabled={!chosen}>
              <FolderOpen /> Choose a folder
            </Button>
          </div>
          <p className="m-0 text-sm text-muted-foreground">
            Nothing is read until you ask something.
          </p>
        </div>
      ) : (
        <Projects
          sessions={state.sessions}
          onOpen={show}
          onNew={(folder) => void begin(folder, chosen?.id)}
          onRemove={code.remove}
          canStart={Boolean(chosen)}
        />
      )}
      {ready.length > 1 ? (
        <label className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Model for a new session</span>
          <select
            className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
            value={chosen?.id ?? ""}
            onChange={(e) => setModel(e.target.value)}
          >
            {ready.map((m) => (
              <option key={m.id} value={m.id}>
                {m.title}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <Rules />
      <Leaves model={chosen} />
    </Page>
  );
}

function Page({
  title,
  lead,
  action,
  children,
}: {
  title: string;
  lead?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto grid w-[min(100%-2rem,56rem)] gap-5 pt-8 pb-16">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1.5">
          <h1 className="m-0 text-2xl font-semibold">{title}</h1>
          {lead ? <p className="m-0 max-w-[60ch] text-muted-foreground">{lead}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function Rules() {
  const item = (ok: boolean, text: string) => (
    <li className="flex items-start gap-2">
      {ok ? (
        <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-ok" />
      ) : (
        <X aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-destructive" />
      )}
      <span>{text}</span>
    </li>
  );
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <section className="grid content-start gap-2 rounded-lg border p-4">
        <h2 className="m-0 flex items-center gap-2 text-base font-semibold">
          <Check aria-hidden="true" className="size-4 text-ok" /> In the folder you choose, the
          agent may
        </h2>
        <ul className="m-0 grid list-none gap-1.5 p-0 text-sm">
          {item(true, "find and read every file")}
          {item(true, "answer questions about the project and plan a change")}
          {item(
            true,
            "change and add files, in “Ask me” and “Work on its own”; every turn can be undone",
          )}
        </ul>
      </section>
      <section className="grid content-start gap-2 rounded-lg border p-4">
        <h2 className="m-0 flex items-center gap-2 text-base font-semibold">
          <Lock aria-hidden="true" className="size-4 text-destructive" /> It cannot
        </h2>
        <ul className="m-0 grid list-none gap-1.5 p-0 text-sm">
          {item(
            false,
            "run a command, a test or a program, or delete a file (not in this version)",
          )}
          {item(false, "read the rest of your home folder: documents, keys, other apps' data")}
          {item(false, "reach the internet")}
          {item(false, "see your model key")}
        </ul>
      </section>
    </div>
  );
}

function Leaves({ model }: { model: CodeModel | undefined }) {
  if (!model) return null;
  return (
    <Notice title="What leaves this computer">
      {model.where === "cloud"
        ? `The parts of files the agent reads are sent to the model you chose: ${model.title}, with your own key.`
        : `Nothing. ${model.title} runs on this computer.`}
    </Notice>
  );
}

function Projects({
  sessions,
  onOpen,
  onNew,
  onRemove,
  canStart,
}: {
  sessions: CodeSession[];
  onOpen: (id: string) => void;
  onNew: (folder: string) => void;
  onRemove: (id: string) => void;
  canStart: boolean;
}) {
  const [asking, setAsking] = useState<CodeSession | null>(null);
  const projects = useMemo(() => {
    const by = new Map<string, CodeSession[]>();
    for (const s of sessions) by.set(s.folder, [...(by.get(s.folder) ?? []), s]);
    return [...by.entries()];
  }, [sessions]);
  return (
    <div className="grid gap-3">
      {projects.map(([folder, list]) => (
        <section key={folder} className="grid gap-2 rounded-lg border bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="grid min-w-0 gap-0.5">
              <h2 className="m-0 flex items-center gap-2 text-base font-semibold">
                <Folder aria-hidden="true" className="size-4 text-muted-foreground" />
                <span className="truncate">{list[0]?.project}</span>
              </h2>
              <code className="truncate text-xs text-muted-foreground">{folder}</code>
            </div>
            <Button size="sm" variant="outline" disabled={!canStart} onClick={() => onNew(folder)}>
              <Plus /> New session
            </Button>
          </div>
          <ul className="m-0 grid list-none gap-1 p-0">
            {list.map((s) => (
              <li key={s.id} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => onOpen(s.id)}
                  className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-start text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {s.working ? (
                    <Spinner className="size-4" />
                  ) : (
                    <CircleDashed aria-hidden="true" className="size-4 text-muted-foreground" />
                  )}
                  <span className="truncate font-medium">{s.title}</span>
                  <span
                    className={cn(
                      "ms-auto shrink-0 text-xs text-muted-foreground",
                      (s.waiting || s.needs_you) && "font-medium text-foreground",
                    )}
                  >
                    {s.waiting
                      ? "Waiting for you"
                      : s.checking
                        ? "Checking"
                        : s.working
                          ? "Working"
                          : s.needs_you
                            ? "Check failed · needs you"
                            : s.result
                              ? `${WORDS[s.result]} · ${s.turns} asked`
                              : s.turns
                                ? `${s.turns} asked`
                                : "Nothing asked yet"}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`Delete the session ${s.title}`}
                  title="Delete this session"
                  onClick={() => setAsking(s)}
                  className="grid size-7 place-items-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Trash2 className="size-4" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {asking ? (
        <ConfirmDialog
          title="Delete this session?"
          message={`“${asking.title}” and what was asked in it are deleted. The folder and its files are not touched.`}
          onCancel={() => setAsking(null)}
          onConfirm={() => {
            onRemove(asking.id);
            setAsking(null);
          }}
        />
      ) : null}
    </div>
  );
}

// ---- a session ---------------------------------------------------------------------------------

type Side = "files" | "changes" | "terminal";
const SIDES: Record<Side, string> = { files: "Files", changes: "Changes", terminal: "Terminal" };

function chipFor(session: CodeSession, thread: TurnView[], busy: string | null, waiting: boolean) {
  if (busy === "stopping") return "Stopping";
  if (waiting) return "Waiting for you";
  if (session.checking) return "Checking";
  if (session.working || busy === "sending") return "Working";
  const last = thread[thread.length - 1];
  if (last?.ended === "error") return "Stopped with a problem";
  return session.mode === "plan" ? "Plan · nothing is changed" : MODES[session.mode].label;
}

function Session({
  api,
  session,
  models,
  thread,
  busy,
  error,
  onDismiss,
  onSend,
  onStop,
  onBack,
  onSetLimit,
  onSetMode,
  onAnswer,
  onUndo,
  onRedo,
  onRunCheck,
  onTryAgain,
  onReload,
  filesTick,
  undoNote,
}: {
  api: CodeApi;
  session: CodeSession;
  models: CodeModel[];
  thread: TurnView[];
  busy: "sending" | "stopping" | null;
  error: string | null;
  onDismiss: () => void;
  onSend: (text: string) => void;
  onStop: () => void;
  onBack: () => void;
  onSetLimit: (usd: number) => void;
  onSetMode: (mode: CodeMode) => Promise<boolean>;
  onAnswer: (askId: string, answer: CodeAnswer) => void;
  onUndo: (turnId: string) => Promise<void>;
  onRedo: (turnId: string) => Promise<void>;
  onRunCheck: () => Promise<void>;
  onTryAgain: () => Promise<void>;
  /** the check was changed or tried in its dialog */
  onReload: () => Promise<void>;
  filesTick: number;
  undoNote: string | null;
}) {
  const [text, setText] = useState("");
  // on a narrow window one pane shows at a time: the chat, the files, or the changes
  const [pane, setPane] = useState<"chat" | Side>("chat");
  // beside the chat, on a wide window: the files, the changes or the person's terminal
  const [side, setSide] = useState<Side>("files");
  const [may, setMay] = useState(false);
  const [check, setCheck] = useState(false);
  const showSide = (which: Side) => {
    setSide(which);
    setPane(which);
  };
  const working = session.working || busy === "sending";
  const waiting = thread.some((t) => t.parts.some((p) => p.kind === "ask" && p.open));
  const carryOut = async () => {
    if (await onSetMode("ask")) onSend(CARRY_OUT);
  };
  const model = models.find((m) => m.id === session.model);
  const end = useRef<HTMLDivElement | null>(null);
  const count = thread.reduce((n, t) => n + t.parts.length, thread.length);
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll when something is added
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [count, working]);
  const submit = () => {
    const ask = text.trim();
    if (!ask || working) return;
    setText("");
    onSend(ask);
  };
  return (
    <div className="flex h-full min-h-0 flex-col" data-workspace>
      <PageHeader title className="flex items-center gap-3 border-b px-4 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden text-sm">
          <button
            type="button"
            onClick={onBack}
            className="rounded-md px-1.5 py-1 text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            Projects
          </button>
          <ChevronRight aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-16 truncate font-semibold">{session.project}</span>
          {session.title !== session.project ? (
            <span className="hidden truncate text-muted-foreground sm:inline">
              · {session.title}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
          <span className="hidden md:inline">{model?.title ?? session.model}</span>
          <output className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-foreground">
            {working ? <Spinner className="size-3" /> : null}
            {chipFor(session, thread, busy, waiting)}
          </output>
          {session.mode === "plan" && !session.result ? null : (
            <CheckWord
              session={session}
              checking={Boolean(session.checking) && working}
              onOpen={() => setCheck(true)}
            />
          )}
          <Cost session={session} model={model} onSetLimit={onSetLimit} />
        </div>
      </PageHeader>
      <div
        className="flex gap-1 border-b px-3 py-1.5 lg:hidden"
        role="tablist"
        aria-label="What to show"
      >
        {(["chat", "files", "changes", "terminal"] as const).map((p) => (
          <button
            key={p}
            type="button"
            role="tab"
            aria-selected={pane === p}
            onClick={() => (p === "chat" ? setPane(p) : showSide(p))}
            className="rounded-md px-3 py-1 text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-selected:bg-accent aria-selected:font-semibold"
          >
            {p === "chat" ? "Chat" : SIDES[p]}
          </button>
        ))}
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(22rem,2fr)_minmax(0,3fr)]">
        <section
          aria-label="Chat"
          className={cn(
            "min-h-0 flex-col lg:flex lg:border-e",
            pane === "chat" ? "flex" : "hidden",
          )}
        >
          <div className="min-h-0 flex-1 overflow-auto">
            <div className="mx-auto grid w-[min(100%-2rem,46rem)] gap-5 py-6">
              {thread.length === 0 ? (
                <div className="grid justify-items-center gap-3 py-10 text-center">
                  <h2 className="m-0 text-xl font-semibold">
                    What do you want to know about {session.project}?
                  </h2>
                  <p className="m-0 max-w-[40ch] text-sm text-muted-foreground">
                    {session.mode === "plan"
                      ? "Ask how something works, or ask for a plan. In Plan the agent reads files and changes none."
                      : "Ask how something works, or ask for a change. Every turn that changes files can be undone."}
                  </p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {STARTERS.map((s) => (
                      <Chip key={s} className="rounded-full" onClick={() => setText(s)}>
                        {s}
                      </Chip>
                    ))}
                  </div>
                </div>
              ) : null}
              {thread.map((turn, n) => (
                <Turn
                  key={turn.id}
                  turn={turn}
                  mode={session.mode}
                  last={n === thread.length - 1}
                  idle={!working}
                  onAnswer={onAnswer}
                  onOpenMay={() => setMay(true)}
                  onShowChanges={() => showSide("changes")}
                  onUndo={onUndo}
                  onRedo={onRedo}
                  onCarryOut={() => void carryOut()}
                  command={session.check_command ?? ""}
                  standing={session.result}
                  onStop={onStop}
                  onRunCheck={() => void onRunCheck()}
                  onTryAgain={() => void onTryAgain()}
                  onOpenCheck={() => setCheck(true)}
                  readOutput={async (id) => (await api.checkOutput(session.id, id)).output}
                />
              ))}
              {error ? (
                <Notice
                  tone="error"
                  title="That did not work"
                  actions={
                    <Button size="sm" variant="ghost" onClick={onDismiss}>
                      Close
                    </Button>
                  }
                >
                  {error}
                </Notice>
              ) : null}
              <div ref={end} />
            </div>
          </div>
          <form
            className="mx-auto w-[min(100%-2rem,46rem)] pb-4"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <div className="grid gap-2 rounded-xl border bg-surface p-2.5 shadow-card">
              <Textarea
                aria-label="Ask about this project"
                placeholder={
                  session.mode === "plan"
                    ? `Ask about ${session.project}, or ask for a plan`
                    : "Ask for a change, or ask a question"
                }
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    submit();
                  }
                }}
                className="max-h-48 min-h-12 resize-none border-0 shadow-none focus-visible:ring-0"
              />
              <div className="flex items-center justify-between gap-2">
                <ModePill
                  mode={session.mode}
                  disabled={working}
                  onChange={(mode) => void onSetMode(mode)}
                  onOpenMay={() => setMay(true)}
                />
                {working ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={onStop}
                    disabled={busy === "stopping"}
                  >
                    <Square /> Stop
                  </Button>
                ) : (
                  <Button type="submit" size="icon-sm" aria-label="Send" disabled={!text.trim()}>
                    <ArrowUp />
                  </Button>
                )}
              </div>
            </div>
          </form>
        </section>
        <div
          className={cn("min-h-0 min-w-0 flex-col lg:flex", pane === "chat" ? "hidden" : "flex")}
        >
          <div
            className="hidden gap-1 border-b px-3 py-1.5 lg:flex"
            role="tablist"
            aria-label="Beside the chat"
          >
            {(["files", "changes", "terminal"] as const).map((p) => (
              <button
                key={p}
                type="button"
                role="tab"
                aria-selected={side === p}
                onClick={() => showSide(p)}
                className="rounded-md px-3 py-1 text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-selected:bg-accent aria-selected:font-semibold"
              >
                {SIDES[p]}
              </button>
            ))}
          </div>
          {side === "files" ? (
            <section aria-label="Files" className="min-h-0 min-w-0 flex-1">
              <Files api={api} sessionId={session.id} project={session.project} tick={filesTick} />
            </section>
          ) : side === "terminal" ? (
            <section aria-label="Terminal" className="min-h-0 min-w-0 flex-1">
              <TerminalPane api={api} sessionId={session.id} project={session.project} />
            </section>
          ) : (
            <section aria-label="Changes" className="min-h-0 min-w-0 flex-1">
              <Changes
                api={api}
                sessionId={session.id}
                tick={filesTick}
                working={working}
                note={undoNote}
                onUndo={onUndo}
                onRedo={onRedo}
              />
            </section>
          )}
        </div>
      </div>
      {may ? <MayDialog api={api} sessionId={session.id} onClose={() => setMay(false)} /> : null}
      {check ? (
        <CheckDialog
          api={api}
          sessionId={session.id}
          working={working}
          onClose={() => setCheck(false)}
          onSaved={() => void onReload()}
        />
      ) : null}
    </div>
  );
}

/** The cost so far in the bar; it opens to what it is made of and the session's limit (mockup `session-cost`). */
function Cost({
  session,
  model,
  onSetLimit,
}: {
  session: CodeSession;
  model: CodeModel | undefined;
  onSetLimit: (usd: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [limit, setLimit] = useState("");
  const box = useRef<HTMLSpanElement | null>(null);
  // it closes on Escape and on a click anywhere else
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);
  const free = model?.where === "this-computer";
  const part = session.cost_limit_usd > 0 ? session.cost_usd / session.cost_limit_usd : 0;
  const wanted = Number(limit);
  return (
    <span className="relative" ref={box}>
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
        className="rounded-md px-1.5 py-0.5 tabular-nums outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      >
        {free ? "No cost" : dollars(session.cost_usd)}
      </button>
      {open ? (
        <div
          // biome-ignore lint/a11y/useSemanticElements: a small window under its button, not a modal
          role="dialog"
          aria-label="This session so far"
          className="absolute end-0 top-full z-20 mt-1.5 grid w-72 gap-2.5 rounded-lg border bg-surface p-3.5 text-sm text-foreground shadow-card"
        >
          <strong>This session so far</strong>
          <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
            <dt className="text-muted-foreground">
              {model?.title ?? session.model}, {session.model_calls} call
              {session.model_calls === 1 ? "" : "s"}
            </dt>
            <dd className="m-0 tabular-nums">{free ? "No cost" : dollars(session.cost_usd)}</dd>
            <dt className="text-muted-foreground">Asked</dt>
            <dd className="m-0 tabular-nums">{session.turns}</dd>
            {free ? null : (
              <>
                <dt className="text-muted-foreground">Limit for this session</dt>
                <dd className="m-0 tabular-nums">{dollars(session.cost_limit_usd)}</dd>
              </>
            )}
          </dl>
          {free ? (
            <p className="m-0 text-xs text-muted-foreground">
              This model runs on this computer. Nothing is paid and nothing leaves it.
            </p>
          ) : (
            <>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                <div
                  className="h-full bg-primary"
                  style={{ width: `${Math.min(100, Math.round(part * 100))}%` }}
                />
              </div>
              <p className="m-0 text-xs text-muted-foreground">
                Paid with your own key. At the limit the agent stops and says so.
              </p>
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (wanted > 0 && wanted <= 100) {
                    onSetLimit(wanted);
                    setLimit("");
                  }
                }}
              >
                <label className="flex items-center gap-1.5 text-xs">
                  <span className="text-muted-foreground">New limit, in dollars</span>
                  <input
                    type="number"
                    min="0.5"
                    max="100"
                    step="0.5"
                    value={limit}
                    onChange={(e) => setLimit(e.target.value)}
                    className="h-7 w-16 rounded-md border border-input bg-transparent px-1.5 text-sm"
                  />
                </label>
                <Button
                  type="submit"
                  size="xs"
                  variant="outline"
                  disabled={!(wanted > 0 && wanted <= 100)}
                >
                  Change
                </Button>
              </form>
            </>
          )}
        </div>
      ) : null}
    </span>
  );
}

type TurnActions = {
  mode: CodeMode;
  /** it is the session's newest turn */
  last: boolean;
  /** the agent is not working */
  idle: boolean;
  onAnswer: (askId: string, answer: CodeAnswer) => void;
  onOpenMay: () => void;
  onShowChanges: () => void;
  onUndo: (turnId: string) => void;
  onRedo: (turnId: string) => void;
  onCarryOut: () => void;
  /** the project's check command */
  command: string;
  /** the session's word now */
  standing: CodeSession["result"];
  onStop: () => void;
  onRunCheck: () => void;
  onTryAgain: () => void;
  onOpenCheck: () => void;
  readOutput: (checkId: string) => Promise<string>;
};

function Turn({ turn, ...actions }: { turn: TurnView } & TurnActions) {
  const knows = turn.parts.some((p) => p.kind === "steps");
  const asking = turn.parts.some((p) => p.kind === "ask" && p.open);
  const checking = turn.parts.some((p) => p.kind === "check" && p.running);
  const checks = turn.parts.filter((p): p is CheckPart => p.kind === "check");
  return (
    <article className="grid gap-3" aria-label={turn.request || "A turn"}>
      {turn.request ? (
        <div className="justify-self-end rounded-2xl bg-accent px-3.5 py-2 text-sm whitespace-pre-wrap">
          {turn.request}
        </div>
      ) : null}
      {!knows && turn.steps > 0 ? (
        <p className="m-0 text-xs text-muted-foreground">
          The agent took {turn.steps} step{turn.steps === 1 ? "" : "s"} in the project.
        </p>
      ) : null}
      {turn.parts.map((part, n) => {
        const key = `${turn.id}-${n}`;
        if (part.kind === "steps") return <Steps key={key} steps={part.steps} />;
        if (part.kind === "ask") {
          return (
            <AskCard
              key={key}
              ask={part.ask}
              open={part.open}
              answer={part.answer}
              onAnswer={(answer) => actions.onAnswer(part.id, answer)}
              onOpenMay={actions.onOpenMay}
            />
          );
        }
        if (part.kind === "round") {
          return (
            <p
              key={key}
              className="m-0 flex items-center gap-3 text-xs text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border"
            >
              Round {part.round} of {part.of}
            </p>
          );
        }
        if (part.kind === "check") {
          return (
            <CheckCard
              key={key}
              part={part}
              command={actions.command}
              needsYou={turn.needsYou}
              last={part === checks[checks.length - 1]}
              canAct={actions.last && actions.idle && !turn.working}
              canUndo={turn.canUndo}
              onStop={actions.onStop}
              onTryAgain={actions.onTryAgain}
              onUndo={() => actions.onUndo(turn.id)}
              onChange={actions.onOpenCheck}
              onRun={actions.onRunCheck}
              readOutput={actions.readOutput}
            />
          );
        }
        if (part.kind === "refusal") {
          return (
            <Notice key={key} tone="info" title="The model declined this request">
              {part.message} Nothing was changed. You can ask in another way.
            </Notice>
          );
        }
        return (
          <div key={key} className="text-sm leading-relaxed">
            <Markdown text={part.text} animating={part.writing} />
          </div>
        );
      })}
      {turn.working && !checking ? (
        <output className="m-0 flex items-center gap-2 text-sm text-muted-foreground">
          {asking ? (
            <>
              <Hand aria-hidden="true" className="size-3.5" /> Waiting for you. Nothing else runs
              until you answer.
            </>
          ) : (
            <>
              <Spinner className="size-3.5" /> Working…
            </>
          )}
        </output>
      ) : null}
      <Ending turn={turn} {...actions} />
    </article>
  );
}

function Steps({ steps }: { steps: Step[] }) {
  const failed = steps.filter((s) => s.status === "error").length;
  const running = steps.some((s) => s.status === "started");
  const [one] = steps;
  const edits = steps.filter((s) => isEdit(s) && s.status === "ok").length;
  const ran = steps.filter((s) => isCommand(s) && s.status !== "refused").length;
  const mark = (s: Step) =>
    s.status === "error" && !isEdit(s) && !isCommand(s)
      ? " · did not work"
      : s.answer === "allowed"
        ? " · allowed for this project"
        : "";
  // a change that ran with no question, because its kind is allowed, is said on the closed line too
  const allowed = steps.filter((s) => s.answer === "allowed").length;
  if (steps.length === 1 && one) {
    return (
      <details className="rounded-lg border text-sm">
        <summary
          className={cn(
            "flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring",
            one.status === "error" && "text-destructive",
          )}
        >
          {running ? <Spinner className="size-3.5" /> : null}
          <span>
            {stepLine(one)}
            {mark(one)}
          </span>
        </summary>
        {one.text ? (
          <pre className="m-0 max-h-60 overflow-auto border-t bg-muted p-2 text-xs whitespace-pre-wrap">
            {one.text}
          </pre>
        ) : null}
      </details>
    );
  }
  return (
    <details className="group rounded-lg border text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ChevronRight
          aria-hidden="true"
          className="size-3.5 transition-transform group-open:rotate-90"
        />
        {running ? <Spinner className="size-3.5" /> : null}
        <span>
          {steps.some((s) => isEdit(s) || isCommand(s))
            ? `Took ${steps.length} steps`
            : `Looked at ${steps.length} things`}
          {edits ? ` · changed ${edits} time${edits === 1 ? "" : "s"}` : ""}
          {ran ? ` · ran ${ran} command${ran === 1 ? "" : "s"}` : ""}
          {allowed ? ` · ${allowed} allowed for this project` : ""}
          {failed ? ` · ${failed} did not work` : ""}
        </span>
      </summary>
      <ul className="m-0 grid list-none gap-1 border-t px-3 py-2">
        {steps.map((step) => (
          <li key={step.id}>
            <details>
              <summary
                className={cn(
                  "cursor-pointer list-none text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring",
                  step.status === "error" && "text-destructive",
                )}
              >
                {stepLine(step)}
                {mark(step)}
              </summary>
              {step.text ? (
                <pre className="mt-1 max-h-60 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">
                  {step.text}
                </pre>
              ) : null}
            </details>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** What a turn left in the project's files, with the way to look at it and to undo it. */
function Changed({ turn, ...actions }: { turn: TurnView } & TurnActions) {
  const n = turn.changed;
  const files = `${n} file${n === 1 ? "" : "s"}`;
  if (turn.undone) {
    return (
      <section
        aria-label="An undone turn"
        className="flex flex-wrap items-center gap-2 rounded-lg border px-3.5 py-2.5 text-sm"
      >
        <Undo2 aria-hidden="true" className="size-4 shrink-0" />
        <span className="flex-1">
          <strong className="font-semibold">You undid this turn.</strong> {files}{" "}
          {n === 1 ? "is" : "are"} back to how {n === 1 ? "it was" : "they were"} before it.
        </span>
        {turn.canRedo && actions.idle ? (
          <Button size="sm" variant="outline" onClick={() => actions.onRedo(turn.id)}>
            <Redo2 /> Bring it back
          </Button>
        ) : null}
      </section>
    );
  }
  return (
    <section
      aria-label="What this turn changed"
      className="grid gap-2 rounded-lg border px-3.5 py-2.5 text-sm"
    >
      <p className="m-0 flex items-start gap-2">
        <FileDiff aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span>
          <strong className="font-semibold">Changed {files}.</strong> {checkedLine(turn)}
        </span>
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={actions.onShowChanges}>
          Look at the changes
        </Button>
        {turn.canUndo && actions.idle ? (
          <Button size="sm" variant="ghost" onClick={() => actions.onUndo(turn.id)}>
            <Undo2 /> Undo this turn
          </Button>
        ) : null}
        {turn.result === "not_checked" && turn.checkWhy === "no_command" && actions.last ? (
          <Button size="sm" variant="ghost" onClick={actions.onOpenCheck}>
            Set a check
          </Button>
        ) : null}
        {turn.result === "not_checked" &&
        turn.checkWhy !== "no_command" &&
        actions.command &&
        actions.last &&
        actions.idle &&
        !turn.parts.some((p) => p.kind === "check") ? (
          <Button size="sm" variant="ghost" onClick={actions.onRunCheck}>
            Run the check now
          </Button>
        ) : null}
      </div>
    </section>
  );
}

/** What the check said of a turn that changed files, in a sentence beside "Changed 2 files". */
function checkedLine(turn: TurnView): string {
  if (turn.result === "passed") {
    return turn.checkWhy === "same_as_last_pass"
      ? "The files are again exactly what passed the check."
      : "The check passed.";
  }
  if (turn.result === "failed") return "The check still fails.";
  if (turn.result === "could_not_check") return "The check could not run, which is not a pass.";
  if (turn.checkWhy === "no_command") return "Not checked: this project has no check yet.";
  if (turn.ended === "stopped") return "Not checked: the turn was stopped first.";
  if (turn.ended === "step_limit") return "Not checked: the agent reached its step limit first.";
  return "Not checked.";
}

function Ending({ turn, ...actions }: { turn: TurnView } & TurnActions) {
  if (turn.working || !turn.ended) return null;
  const changed = turn.changed > 0;
  const nothing = changed ? "" : " Nothing was changed.";
  const card = changed ? <Changed turn={turn} {...actions} /> : null;
  if (turn.ended === "finished") {
    if (changed) return card;
    // a file the project ignores is changed without being one of the turn's changes: say that,
    // and never "no file was changed" after a change the person has just seen
    const outside = turn.parts.some(
      (p) => p.kind === "steps" && p.steps.some((st) => isEdit(st) && st.status === "ok"),
    );
    if (outside) {
      return (
        <p className="m-0 text-sm text-muted-foreground">
          This turn changed only files Undo cannot put back.
        </p>
      );
    }
    if (actions.mode !== "plan") {
      return (
        <p className="m-0 text-sm text-muted-foreground">
          No file was changed.
          {turn.result ? ` The last check still stands: ${WORDS[turn.result].toLowerCase()}.` : ""}
        </p>
      );
    }
    return (
      <section
        aria-label="A plan"
        className="grid gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3.5 py-3 text-sm"
      >
        <h3 className="m-0 flex items-center gap-2 text-sm font-semibold">
          <ListChecks aria-hidden="true" className="size-4" /> Nothing was changed
        </h3>
        <p className="m-0 text-muted-foreground">
          In Plan the agent reads files and changes none.
          {actions.last ? " Carrying the plan out switches this session to “Ask me”." : ""}
        </p>
        {actions.last && actions.idle ? (
          <div>
            <Button size="sm" onClick={actions.onCarryOut}>
              Carry out this plan
            </Button>
          </div>
        ) : null}
      </section>
    );
  }
  if (turn.ended === "stopped") {
    return (
      <>
        <p className="m-0 text-sm text-muted-foreground">You stopped this turn.{nothing}</p>
        {card}
      </>
    );
  }
  if (turn.ended === "step_limit") {
    return (
      <>
        <Notice tone="warn" title="The agent stopped at its step limit">
          It used every step one turn allows.{nothing} Ask it to go on, or ask a narrower question.
        </Notice>
        {card}
      </>
    );
  }
  if (turn.ended === "error") {
    return (
      <>
        <Notice tone="error" title="The turn stopped with a problem">
          {turn.detail || "The coding engine reported an error."}
          {nothing}
        </Notice>
        {card}
      </>
    );
  }
  return card;
}
