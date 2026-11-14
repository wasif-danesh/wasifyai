"use client";
// Code (ADR-0101; mockups in docs/spikes/coding-mockups.html): where coding lives, the projects, and a
// session. This stage has Plan only: the agent reads the project and answers or gives a plan; it changes
// nothing. The window calls the coding product's routes and never the coding engine.
import type { CodeApi, CodeModel, CodeSession } from "@wasifyai/client";
import {
  ArrowUp,
  Check,
  ChevronRight,
  CircleDashed,
  Folder,
  FolderOpen,
  ListChecks,
  Lock,
  Plus,
  Square,
  Trash2,
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
import { Files } from "./Files";
import { type Step, type TurnView, buildThread, stepLine } from "./thread";
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
        thread={buildThread(state.turns, state.events)}
        busy={state.busy}
        error={state.error}
        onDismiss={code.dismiss}
        onSend={code.send}
        onStop={code.stop}
        onBack={() => show(null)}
        onSetLimit={code.setLimit}
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
          : "Choose the folder of a project. An agent reads it and answers your questions about it, or gives you a plan for a change."
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
        </ul>
      </section>
      <section className="grid content-start gap-2 rounded-lg border p-4">
        <h2 className="m-0 flex items-center gap-2 text-base font-semibold">
          <Lock aria-hidden="true" className="size-4 text-destructive" /> It cannot
        </h2>
        <ul className="m-0 grid list-none gap-1.5 p-0 text-sm">
          {item(false, "change, add or delete a file, or run a command (not in this version)")}
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
                  <span className="ms-auto shrink-0 text-xs text-muted-foreground">
                    {s.working ? "Working" : s.turns ? `${s.turns} asked` : "Nothing asked yet"}
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

function chipFor(session: CodeSession, thread: TurnView[], busy: string | null) {
  if (busy === "stopping") return "Stopping";
  if (session.working || busy === "sending") return "Working";
  const last = thread[thread.length - 1];
  if (last?.ended === "error") return "Stopped with a problem";
  return "Plan · nothing is changed";
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
}) {
  const [text, setText] = useState("");
  // on a narrow window one pane shows at a time: the chat, or the files
  const [pane, setPane] = useState<"chat" | "files">("chat");
  const working = session.working || busy === "sending";
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
        <div className="flex min-w-0 flex-1 items-center gap-1.5 text-sm">
          <button
            type="button"
            onClick={onBack}
            className="rounded-md px-1.5 py-1 text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            Projects
          </button>
          <ChevronRight aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="max-w-[40%] shrink-0 truncate font-semibold">{session.project}</span>
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
            {chipFor(session, thread, busy)}
          </output>
          <Cost session={session} model={model} onSetLimit={onSetLimit} />
        </div>
      </PageHeader>
      <div
        className="flex gap-1 border-b px-3 py-1.5 lg:hidden"
        role="tablist"
        aria-label="What to show"
      >
        {(["chat", "files"] as const).map((p) => (
          <button
            key={p}
            type="button"
            role="tab"
            aria-selected={pane === p}
            onClick={() => setPane(p)}
            className="rounded-md px-3 py-1 text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-selected:bg-accent aria-selected:font-semibold"
          >
            {p === "chat" ? "Chat" : "Files"}
          </button>
        ))}
      </div>
      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(22rem,2fr)_3fr]">
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
                    Ask how something works, or ask for a plan. In Plan the agent reads files and
                    changes none.
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
              {thread.map((turn) => (
                <Turn key={turn.id} turn={turn} />
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
                placeholder={`Ask about ${session.project}, or ask for a plan`}
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
                <span
                  className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
                  title="In Plan the agent reads files and changes none. Modes that change files come in a later version."
                >
                  <ListChecks aria-hidden="true" className="size-3.5" /> Plan
                </span>
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
        <section
          aria-label="Files"
          className={cn("min-h-0 lg:block", pane === "files" ? "block" : "hidden")}
        >
          <Files api={api} sessionId={session.id} project={session.project} />
        </section>
      </div>
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

function Turn({ turn }: { turn: TurnView }) {
  const knows = turn.parts.some((p) => p.kind === "steps");
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
      {turn.working ? (
        <output className="m-0 flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner className="size-3.5" /> Working…
        </output>
      ) : null}
      <Ending turn={turn} />
    </article>
  );
}

function Steps({ steps }: { steps: Step[] }) {
  const failed = steps.filter((s) => s.status === "error").length;
  const running = steps.some((s) => s.status === "started");
  const [one] = steps;
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
            {one.status === "error" ? " · did not work" : ""}
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
          Looked at {steps.length} things
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
                {step.status === "error" ? " · did not work" : ""}
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

function Ending({ turn }: { turn: TurnView }) {
  if (turn.working || !turn.ended) return null;
  if (turn.ended === "finished") {
    return (
      <section
        aria-label="A plan"
        className="grid gap-1 rounded-lg border border-primary/30 bg-primary/5 px-3.5 py-3 text-sm"
      >
        <h3 className="m-0 flex items-center gap-2 text-sm font-semibold">
          <ListChecks aria-hidden="true" className="size-4" /> Nothing was changed
        </h3>
        <p className="m-0 text-muted-foreground">In Plan the agent reads files and changes none.</p>
      </section>
    );
  }
  if (turn.ended === "stopped") {
    return (
      <p className="m-0 text-sm text-muted-foreground">
        You stopped this turn. Nothing was changed.
      </p>
    );
  }
  if (turn.ended === "step_limit") {
    return (
      <Notice tone="warn" title="The agent stopped at its step limit">
        It used every step one turn allows. Nothing was changed. Ask it to go on, or ask a narrower
        question.
      </Notice>
    );
  }
  if (turn.ended === "error") {
    return (
      <Notice tone="error" title="The turn stopped with a problem">
        {turn.detail || "The coding engine reported an error."} Nothing was changed.
      </Notice>
    );
  }
  return null;
}
