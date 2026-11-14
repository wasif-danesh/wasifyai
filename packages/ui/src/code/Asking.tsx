"use client";
// Asking (mockups `ask`, `ask-answered`, `session-mode`, `project-may`): the card the agent's question arrives
// as, the mode a session works in, and what a person allowed for the project. The kinds of request are a
// fixed list; a person allows a kind for one project and can take that back.
import type {
  CodeAnswer,
  CodeApi,
  CodeAsk,
  CodeAskKind,
  CodeMode,
  CodeProject,
} from "@wasifyai/client";
import { Check, ChevronDown, ChevronRight, Hand, ListChecks, Shield, X, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Modal } from "../components/dialog";
import { Spinner } from "../components/spinner";

export const MODES: Record<CodeMode, { label: string; icon: typeof Hand; says: string }> = {
  plan: {
    label: "Plan",
    icon: ListChecks,
    says: "Reads the project and writes a plan. Changes no file.",
  },
  ask: {
    label: "Ask me",
    icon: Hand,
    says: "Changes files in this folder. Asks you before it changes a file Undo cannot put back. You can allow that once for the whole project.",
  },
  own: {
    label: "Work on its own",
    icon: Zap,
    says: "Does not ask before a change. It still cannot leave this folder or reach the internet, and every turn can be undone.",
  },
};

/** Each kind of request in words: what the card is called, the rule, and what allowing it covers. */
export const KINDS: Record<
  CodeAskKind,
  { title: string; rule: string; allowed: string; covers: string; why: string }
> = {
  not_undoable: {
    title: "The agent wants to change a file Undo cannot put back",
    rule: "Ask before changing files Undo cannot put back",
    allowed: "changing files Undo cannot put back",
    covers: "the agent changes files Undo cannot put back",
    why: "Your project ignores this file, or it is inside a .git folder. Wasify AI keeps no copy of such files, so Undo will not put this change back.",
  },
  delete: {
    title: "The agent wants to delete files",
    rule: "Ask before deleting files",
    allowed: "deleting files",
    covers: "the agent deletes files",
    why: "Deleting is asked first.",
  },
  install: {
    title: "The agent wants to install packages",
    rule: "Ask before installing packages",
    allowed: "installing packages",
    covers: "the agent installs packages",
    why: "Installing fetches programs from the internet and is asked first.",
  },
};

/** The approval card. While it is open nothing has run; the answer goes to the engine. */
export function AskCard({
  ask,
  open,
  answer,
  onAnswer,
  onOpenMay,
}: {
  ask: CodeAsk;
  open: boolean;
  answer: CodeAnswer | "";
  onAnswer: (answer: CodeAnswer) => void;
  onOpenMay: () => void;
}) {
  const kind = KINDS[ask.ask];
  const [sent, setSent] = useState<CodeAnswer | null>(null);
  const say = (value: CodeAnswer) => {
    setSent(value);
    onAnswer(value);
  };
  return (
    <section
      aria-label={kind.title}
      className="grid gap-2.5 rounded-lg border border-warn/40 bg-warn/5 px-3.5 py-3 text-sm"
    >
      <h3 className="m-0 flex items-center gap-2 text-sm font-semibold">
        <Hand aria-hidden="true" className="size-4 shrink-0" /> {kind.title}
      </h3>
      <code className="block overflow-x-auto rounded-md bg-muted px-2 py-1.5 text-xs whitespace-pre">
        {ask.path || ask.tool}
      </code>
      {ask.says ? <p className="m-0">It says: “{ask.says}”</p> : null}
      <p className="m-0 text-muted-foreground">
        <strong className="font-medium text-foreground">Why you are asked:</strong> the rule “
        {kind.rule}”. {kind.why}
        {ask.steps > 1 ? ` ${ask.steps} steps wait together; your answer is for all of them.` : ""}
      </p>
      {open ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => say("yes")} disabled={sent !== null}>
              Yes, change it
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => say("allow")}
              disabled={sent !== null}
            >
              Allow for this project
            </Button>
            <Button size="sm" variant="ghost" onClick={() => say("no")} disabled={sent !== null}>
              No
            </Button>
            {sent !== null ? <Spinner className="size-3.5" /> : null}
          </div>
          <p className="m-0 text-xs text-muted-foreground">
            “Allow for this project” changes it and stops asking before {kind.covers} in{" "}
            {ask.project}. You can take it back in{" "}
            <button type="button" className="underline underline-offset-2" onClick={onOpenMay}>
              What this project may do
            </button>
            .
          </p>
        </>
      ) : answer === "allow" ? (
        <p className="m-0 flex items-start gap-2">
          <Shield aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-ok" />
          <span>
            You allowed {kind.allowed} for this project.{" "}
            <button type="button" className="underline underline-offset-2" onClick={onOpenMay}>
              Take it back
            </button>
          </span>
        </p>
      ) : answer === "yes" ? (
        <p className="m-0 flex items-center gap-2">
          <Check aria-hidden="true" className="size-4 shrink-0 text-ok" /> You said yes.
        </p>
      ) : answer === "no" ? (
        <p className="m-0 flex items-center gap-2">
          <X aria-hidden="true" className="size-4 shrink-0" /> You said no. The agent was told and
          the file was not changed.
        </p>
      ) : (
        <p className="m-0 text-muted-foreground">
          The turn ended before this was answered. The file was not changed.
        </p>
      )}
    </section>
  );
}

/** The mode, as a pill in the box you write in; it opens to the three modes and the project's list. */
export function ModePill({
  mode,
  disabled,
  onChange,
  onOpenMay,
}: {
  mode: CodeMode;
  /** the agent is working: Plan cannot be entered or left until it has ended */
  disabled: boolean;
  onChange: (mode: CodeMode) => void;
  onOpenMay: () => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement | null>(null);
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
  const now = MODES[mode];
  const Icon = now.icon;
  return (
    <span className="relative" ref={box}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`How much the agent asks: ${now.label}`}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Icon aria-hidden="true" className="size-3.5" /> {now.label}
        <ChevronDown aria-hidden="true" className="size-3" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="How much the agent asks"
          className="absolute start-0 bottom-full z-20 mb-1.5 grid w-80 max-w-[calc(100vw-3rem)] gap-0.5 rounded-lg border bg-surface p-1.5 text-sm shadow-card"
        >
          {(Object.keys(MODES) as CodeMode[]).map((key) => {
            const m = MODES[key];
            const MIcon = m.icon;
            // to or from Plan the agent's tools change, which cannot happen in the middle of a turn
            const blocked = disabled && key !== mode && (key === "plan" || mode === "plan");
            return (
              <button
                key={key}
                type="button"
                role="menuitemradio"
                aria-checked={key === mode}
                disabled={blocked}
                onClick={() => {
                  setOpen(false);
                  if (key !== mode) onChange(key);
                }}
                className="grid grid-cols-[auto_1fr_auto] items-start gap-x-2 rounded-md px-2 py-1.5 text-start outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              >
                <MIcon aria-hidden="true" className="mt-0.5 size-4" />
                <span className="font-medium">{m.label}</span>
                {key === mode ? <Check aria-hidden="true" className="mt-0.5 size-4" /> : <span />}
                <span className="col-start-2 col-end-4 text-xs text-muted-foreground">
                  {m.says}
                  {blocked ? " Not while the agent is working." : ""}
                </span>
              </button>
            );
          })}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onOpenMay();
            }}
            className="mt-0.5 flex items-center gap-2 rounded-md border-t px-2 py-2 text-start outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Shield aria-hidden="true" className="size-4" />
            <span className="flex-1">What this project may do</span>
            <ChevronRight aria-hidden="true" className="size-3.5" />
          </button>
        </div>
      ) : null}
    </span>
  );
}

/** "What this project may do": the mode, and each kind of request with Allow or Remove. */
export function MayDialog({
  api,
  sessionId,
  onClose,
}: {
  api: CodeApi;
  sessionId: string;
  onClose: () => void;
}) {
  const [project, setProject] = useState<CodeProject | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let gone = false;
    api
      .project(sessionId)
      .then((p) => {
        if (!gone) setProject(p);
      })
      .catch(() => {
        if (!gone) setProblem("The list could not be read.");
      });
    return () => {
      gone = true;
    };
  }, [api, sessionId]);
  const set = async (kind: CodeAskKind, allowed: boolean) => {
    try {
      setProject(await api.allow(sessionId, kind, allowed));
      setProblem(null);
    } catch {
      setProblem("That could not be changed.");
    }
  };
  return (
    <Modal
      label={project ? `What ${project.project} may do` : "What this project may do"}
      onClose={onClose}
    >
      {project ? (
        <>
          <p className="m-0 text-sm text-muted-foreground">
            This session is in “{MODES[project.mode].label}”. {MODES[project.mode].says}
          </p>
          <ul className="m-0 grid list-none gap-2 p-0">
            {project.kinds.map((k) => (
              <li
                key={k.id}
                className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
              >
                <span className="grid gap-0.5">
                  <span className="font-medium">
                    {KINDS[k.id].allowed.charAt(0).toUpperCase() + KINDS[k.id].allowed.slice(1)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {k.allowed ? "Allowed: the agent does not ask." : "Asks each time."}
                    {k.asked_now
                      ? ""
                      : " It comes up once the agent can run commands, in a later version."}
                  </span>
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`${k.allowed ? "Remove" : "Allow"}: ${KINDS[k.id].allowed}`}
                  onClick={() => void set(k.id, !k.allowed)}
                >
                  {k.allowed ? "Remove" : "Allow"}
                </Button>
              </li>
            ))}
          </ul>
          <p className="m-0 text-xs text-muted-foreground">
            This list is for {project.project} and for you only. Another project starts with nothing
            allowed. Whatever is allowed, the agent cannot leave this folder or reach the internet,
            and what it does is still shown in the chat.
          </p>
        </>
      ) : problem ? null : (
        <Spinner />
      )}
      {problem ? <p className="m-0 text-sm text-destructive">{problem}</p> : null}
      <div className="flex justify-end">
        <Button onClick={onClose}>Done</Button>
      </div>
    </Modal>
  );
}
