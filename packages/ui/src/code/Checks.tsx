"use client";
// The check (mockups `check-setup`, `check-running`, `check-results`, `check-failed-round`,
// `check-needs-you`): after a turn that changed files the app runs the project's own command. The card says
// one of four words, and a check that could not run is never shown as passed. The dialog sets the command,
// suggested from the project's files, and tries it at once.
import type { CodeApi, CodeCheck, CodeCheckInfo, CodeSession } from "@wasifyai/client";
import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleX,
  Lock,
  Play,
  Square,
  Undo2,
} from "lucide-react";
import { useEffect, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { Modal } from "../components/dialog";
import { Input } from "../components/input";
import { Spinner } from "../components/spinner";
import type { CheckPart } from "./thread";

type Word = CodeSession["result"];

/** The check's word as a person reads it. */
export const WORDS: Record<Exclude<Word, "">, string> = {
  passed: "Passed",
  failed: "Check failed",
  not_checked: "Not checked",
  could_not_check: "Could not check",
};

const TONE: Record<Exclude<Word, "">, string> = {
  passed: "text-ok",
  failed: "text-destructive",
  not_checked: "text-muted-foreground",
  could_not_check: "text-warn",
};

function Mark({ word, className }: { word: Word; className?: string }) {
  const Icon =
    word === "passed"
      ? CircleCheck
      : word === "failed"
        ? CircleX
        : word === "could_not_check"
          ? CircleAlert
          : CircleDashed;
  return (
    <Icon
      aria-hidden="true"
      className={cn("size-4 shrink-0", word ? TONE[word] : "text-muted-foreground", className)}
    />
  );
}

/** Why a check has no verdict, in a sentence. Never a pass. */
export function whyNot(why: string, command: string): string {
  if (why === "missing_command") {
    return `The check did not run: the command ${command ? `“${command}” ` : ""}was not found or cannot be run. That is not a pass.`;
  }
  if (why === "time_limit")
    return "The check took longer than it is allowed and was stopped. That is not a pass.";
  if (why === "crashed") return "The check stopped with a crash of its own. That is not a pass.";
  if (why === "could_not_start") return "The check could not be started. That is not a pass.";
  if (why === "stopped") return "The check was stopped before it could finish.";
  return "The check did not run. That is not a pass.";
}

function took(seconds: number): string {
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  if (seconds < 90) return `${Math.round(seconds)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

/** The word in the session's bar; it opens the check's dialog. */
export function CheckWord({
  session,
  checking,
  onOpen,
}: {
  session: CodeSession;
  checking: boolean;
  onOpen: () => void;
}) {
  const word = session.result;
  const label = checking
    ? "Checking"
    : word === "failed" && session.needs_you
      ? "Check failed · needs you"
      : word
        ? WORDS[word]
        : session.check_command
          ? "Not checked yet"
          : "No check";
  return (
    <button
      type="button"
      onClick={onOpen}
      title="The check for this project"
      aria-label={`The check: ${label}. Change the check`}
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
    >
      {checking ? <Spinner className="size-3" /> : <Mark word={word} className="size-3.5" />}
      {label}
    </button>
  );
}

export type CheckActions = {
  /** the agent is not working, and this is the session's newest turn */
  canAct: boolean;
  canUndo: boolean;
  onStop: () => void;
  onTryAgain: () => void;
  onUndo: () => void;
  onChange: () => void;
  onRun: () => void;
  /** read the whole output of a check */
  readOutput: (checkId: string) => Promise<string>;
};

/** One run of the check, in the chat. */
export function CheckCard({
  part,
  command,
  needsYou,
  last,
  ...actions
}: {
  part: CheckPart;
  /** the project's check command, for a check that is still running */
  command: string;
  /** the turn ended here and a person must decide */
  needsYou: boolean;
  /** it is the turn's last check */
  last: boolean;
} & CheckActions) {
  const [whole, setWhole] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const shown = part.command || command;
  const round = part.round > 0 ? `round ${part.round} of ${part.of}` : "run by you";
  if (part.running) {
    return (
      <section
        aria-label="The check is running"
        className="grid gap-2 rounded-lg border px-3.5 py-3 text-sm"
      >
        <h3 className="m-0 flex items-center gap-2 text-sm font-semibold">
          <Spinner className="size-4" /> Checking
        </h3>
        <p className="m-0 text-muted-foreground">Wasify AI is running the project’s check.</p>
        <Facts command={shown} items={[round]} />
        <div>
          <Button size="sm" variant="outline" onClick={actions.onStop}>
            <Square /> Stop the check
          </Button>
        </div>
      </section>
    );
  }
  const word = part.result || "not_checked";
  const title =
    word === "failed" && needsYou && last
      ? "Check failed · needs you"
      : word === "failed"
        ? "Check failed"
        : word === "passed"
          ? "Check passed"
          : WORDS[word];
  const line =
    word === "passed"
      ? "The check ran after this turn and found nothing wrong."
      : word === "failed"
        ? needsYou && last
          ? part.round >= part.of
            ? `The check still fails after ${part.of} rounds, so the agent has stopped.`
            : "The check still fails and the agent changed nothing more, so it has stopped."
          : part.sentBack
            ? "Sent back to the agent: the command, its exit code and the end of the output."
            : "The check failed."
        : whyNot(part.why, shown);
  const facts = [
    part.exitCode !== null && word === "failed" ? `exit code ${part.exitCode}` : "",
    part.seconds ? took(part.seconds) : "",
    round,
  ].filter(Boolean);
  const output = whole ?? part.tail;
  const showAll = async () => {
    if (!part.id) return;
    setReading(true);
    try {
      setWhole(await actions.readOutput(part.id));
    } catch {
      setWhole("The output could not be read.");
    }
    setReading(false);
  };
  const act = last && actions.canAct;
  return (
    <section
      aria-label={title}
      className={cn(
        "grid gap-2 rounded-lg border px-3.5 py-3 text-sm",
        word === "failed" && "border-destructive/40",
        word === "could_not_check" && "border-warn/40",
      )}
    >
      <h3 className="m-0 flex items-center gap-2 text-sm font-semibold">
        <Mark word={word} /> {title}
      </h3>
      <p className="m-0 text-muted-foreground">{line}</p>
      <Facts command={shown} items={facts} />
      {part.tests.length ? (
        <div className="grid gap-1">
          <p className="m-0 font-medium">The agent changed or deleted tests in this turn</p>
          <ul className="m-0 grid list-none gap-0.5 p-0 text-xs">
            {part.tests.map((t) => (
              <li key={t}>
                <code>{t}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {word !== "passed" || whole !== null ? (
        <details open={word === "failed" && (needsYou || part.sentBack)}>
          <summary className="cursor-pointer text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
            {word === "failed" && needsYou && last ? "What still fails" : "The end of the output"}
          </summary>
          {output ? (
            <pre className="mt-1 max-h-72 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">
              {output}
            </pre>
          ) : (
            <p className="m-0 mt-1 text-xs text-muted-foreground">
              {part.id ? "Not read yet." : "It printed nothing."}
            </p>
          )}
          {part.id && whole === null ? (
            <Button
              size="sm"
              variant="ghost"
              className="mt-1"
              onClick={() => void showAll()}
              disabled={reading}
            >
              Show the whole output
            </Button>
          ) : null}
        </details>
      ) : null}
      {act && word !== "passed" ? (
        <div className="flex flex-wrap items-center gap-2">
          {word === "failed" && part.round > 0 ? (
            <Button size="sm" onClick={actions.onTryAgain}>
              Try {part.of} more rounds
            </Button>
          ) : null}
          {word === "could_not_check" ? (
            <Button size="sm" onClick={actions.onChange}>
              Change the check
            </Button>
          ) : null}
          {word !== "failed" || part.round === 0 ? (
            <Button size="sm" variant="outline" onClick={actions.onRun}>
              <Play />{" "}
              {word === "could_not_check"
                ? "Try again"
                : part.round === 0
                  ? "Run the check again"
                  : "Run the check now"}
            </Button>
          ) : null}
          {actions.canUndo ? (
            <Button size="sm" variant="outline" onClick={actions.onUndo}>
              <Undo2 /> Undo this turn
            </Button>
          ) : null}
          {word === "failed" ? (
            <Button size="sm" variant="ghost" onClick={actions.onChange}>
              Change the check
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function Facts({ command, items }: { command: string; items: string[] }) {
  return (
    <p className="m-0 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      {command ? <code className="rounded bg-muted px-1.5 py-0.5">{command}</code> : null}
      {items.map((item) => (
        <span key={item}>{item}</span>
      ))}
    </p>
  );
}

const LIMITS = [
  [60, "1 minute"],
  [300, "5 minutes"],
  [600, "10 minutes"],
  [1800, "30 minutes"],
  [3600, "1 hour"],
] as const;

/** The check's dialog: the command, the suggestions, "Try it now", and no check at all. */
export function CheckDialog({
  api,
  sessionId,
  working,
  onClose,
  onSaved,
}: {
  api: CodeApi;
  sessionId: string;
  /** the agent is working: the check can be changed, and not tried */
  working: boolean;
  onClose: () => void;
  /** the check was saved or tried: the session's word may have changed */
  onSaved: () => void;
}) {
  const [info, setInfo] = useState<CodeCheckInfo | null>(null);
  const [command, setCommand] = useState("");
  const [none, setNone] = useState(false);
  const [limit, setLimit] = useState(600);
  const [problem, setProblem] = useState<string | null>(null);
  const [trying, setTrying] = useState(false);
  const [tried, setTried] = useState<CodeCheck | null>(null);
  const commandId = useId();
  useEffect(() => {
    let gone = false;
    api
      .check(sessionId)
      .then((found) => {
        if (gone) return;
        setInfo(found);
        setCommand(found.command || found.suggested[0]?.command || "");
        setLimit(found.limit_s);
      })
      .catch(() => {
        if (!gone) setProblem("The check could not be read.");
      });
    return () => {
      gone = true;
    };
  }, [api, sessionId]);
  const wanted = none ? "" : command.trim();
  const save = async (): Promise<boolean> => {
    try {
      setInfo(await api.setCheck(sessionId, wanted, limit));
      setProblem(null);
      return true;
    } catch (e) {
      setProblem(e instanceof Error && e.message ? e.message : "The check could not be saved.");
      return false;
    }
  };
  const tryNow = async () => {
    setTrying(true);
    setTried(null);
    if (await save()) {
      try {
        setTried((await api.runCheck(sessionId)).check);
      } catch (e) {
        setProblem(e instanceof Error && e.message ? e.message : "The check could not be run.");
      }
      onSaved();
    }
    setTrying(false);
  };
  const first = info?.suggested[0];
  const others = (info?.suggested ?? []).filter((s) => s.command !== command.trim());
  return (
    <Modal label={info ? `The check for ${info.project}` : "The check"} onClose={onClose}>
      {info ? (
        <>
          <p className="m-0 text-sm text-muted-foreground">
            After a turn that changed files, Wasify AI runs this command in the project. If it
            fails, the agent gets the end of the output and tries again, up to {info.rounds} times.
          </p>
          <div className="grid gap-1.5 text-sm">
            <label htmlFor={commandId} className="font-medium">
              Command
            </label>
            <Input
              id={commandId}
              value={command}
              disabled={none}
              onChange={(e) => {
                setCommand(e.target.value);
                setTried(null);
              }}
              placeholder="npm test"
              className="font-mono"
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
            />
          </div>
          {first && first.command === command.trim() ? (
            <p className="m-0 text-xs text-muted-foreground">
              Suggested because {plain(first.why)}.
            </p>
          ) : null}
          {!info.suggested.length && !info.command ? (
            <p className="m-0 text-xs text-muted-foreground">
              Nothing in this project’s files suggests a check. Type the command that runs its
              tests.
            </p>
          ) : null}
          {others.length ? (
            <div className="grid gap-1.5">
              <span className="text-xs text-muted-foreground">
                Other commands found in this project:
              </span>
              <div className="flex flex-wrap gap-1.5">
                {others.map((s) => (
                  <button
                    key={s.command}
                    type="button"
                    disabled={none}
                    title={plain(s.why)}
                    onClick={() => {
                      setCommand(s.command);
                      setTried(null);
                    }}
                    className="rounded-full border px-2.5 py-0.5 font-mono text-xs outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                  >
                    {s.command}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void tryNow()}
              disabled={trying || working || !wanted}
            >
              {trying ? <Spinner className="size-3.5" /> : <Play />} Try it now
            </Button>
            {tried ? (
              <output className="flex items-center gap-1.5">
                <Mark word={tried.result} />
                {tried.result === "passed"
                  ? `Passed in ${took(tried.seconds)}`
                  : tried.result === "failed"
                    ? `Failed with exit code ${tried.exit_code} in ${took(tried.seconds)}`
                    : whyNot(tried.why, tried.command)}
              </output>
            ) : working ? (
              <span className="text-xs text-muted-foreground">
                It can be tried when the agent has stopped.
              </span>
            ) : null}
          </div>
          <Checkbox
            checked={none}
            onCheckedChange={setNone}
            label="No check for this project"
            hint="Every turn that changes files then ends “not checked”."
          />
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
              For experts
            </summary>
            <label className="mt-2 grid max-w-56 gap-1.5">
              <span className="font-medium">Stop a check after</span>
              <select
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="h-9 rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {LIMITS.some(([s]) => s === limit) ? null : (
                  <option value={limit}>{limit} seconds</option>
                )}
                {LIMITS.map(([s, label]) => (
                  <option key={s} value={s}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </details>
          <p className="m-0 flex items-start gap-2 text-xs text-muted-foreground">
            <Lock aria-hidden="true" className="mt-0.5 size-3 shrink-0" />
            <span>
              Kept by Wasify AI, outside the project, where the agent cannot change it. The check
              runs inside the project’s protected area: it can write only inside the project.
            </span>
          </p>
        </>
      ) : problem ? null : (
        <Spinner className="size-4" />
      )}
      {problem ? (
        <p role="alert" className="m-0 text-sm text-destructive">
          {problem}
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          disabled={!info || trying}
          onClick={async () => {
            if (await save()) {
              onSaved();
              onClose();
            }
          }}
        >
          Save the check
        </Button>
      </div>
    </Modal>
  );
}

/** A reason from the engine with its code marks taken off, for a sentence. */
function plain(why: string): string {
  return why.replaceAll("`", "");
}
