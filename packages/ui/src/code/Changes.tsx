"use client";
// The Changes tab of a coding session (mockups `changes`, `changes-undone`, `empty-changes`): one turn at a
// time, the files it changed, each file before and after, and "Undo this turn". An undone turn stays in the
// list with "Bring it back".
import type { CodeApi, CodeChange, CodeChangeFile } from "@wasifyai/client";
import { FileDiff, Info, Redo2, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { EmptyState } from "../components/empty-state";
import { Notice } from "../components/notice";
import { Segmented } from "../components/segmented";
import { Spinner } from "../components/spinner";

const WHAT = { added: "added", changed: "changed", deleted: "deleted" } as const;
const MARK = { added: "+", changed: "~", deleted: "−" } as const;

const timeOf = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

export function Changes({
  api,
  sessionId,
  tick,
  working,
  note,
  onUndo,
  onRedo,
}: {
  api: CodeApi;
  sessionId: string;
  /** it goes up when the files may have changed: the list is read again */
  tick: number;
  working: boolean;
  /** what the last undo said beside doing it */
  note: string | null;
  onUndo: (turnId: string) => Promise<void> | void;
  onRedo: (turnId: string) => Promise<void> | void;
}) {
  const [items, setItems] = useState<CodeChange[] | null>(null);
  const [turnId, setTurnId] = useState<string | null>(null);
  const [path, setPath] = useState<string | null>(null);
  const [file, setFile] = useState<CodeChangeFile | null>(null);
  const [side, setSide] = useState<"both" | "before" | "after">("both");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `tick` says the files may have changed
  useEffect(() => {
    let gone = false;
    api
      .changes(sessionId)
      .then((found) => {
        if (gone) return;
        setItems(found);
        setProblem(null);
        // the newest turn is shown, unless the person is looking at one that is still there
        setTurnId((was) =>
          was && found.some((c) => c.turn_id === was) ? was : (found[0]?.turn_id ?? null),
        );
      })
      .catch(() => {
        if (!gone) setProblem("The changes could not be read.");
      });
    return () => {
      gone = true;
    };
  }, [api, sessionId, tick]);

  const turn = items?.find((c) => c.turn_id === turnId) ?? null;
  const first = turn?.files[0]?.path ?? null;
  const shown = turn?.files.some((f) => f.path === path) ? path : first;

  useEffect(() => {
    if (!turnId || !shown) {
      setFile(null);
      return;
    }
    let gone = false;
    setFile(null);
    api
      .change(sessionId, turnId, shown)
      .then((f) => {
        if (!gone) setFile(f);
      })
      .catch(() => {
        if (!gone) setProblem("That file could not be shown.");
      });
    return () => {
      gone = true;
    };
  }, [api, sessionId, turnId, shown]);

  const put = async (back: boolean) => {
    if (!turn) return;
    setBusy(true);
    try {
      await (back ? onUndo(turn.turn_id) : onRedo(turn.turn_id));
    } finally {
      setBusy(false);
    }
  };

  if (items === null) {
    return (
      <div className="grid h-full place-items-center">
        {problem ? <p className="m-0 text-sm text-destructive">{problem}</p> : <Spinner />}
      </div>
    );
  }
  if (items.length === 0 || !turn) {
    return (
      <EmptyState
        size="sm"
        icon={FileDiff}
        title="No changes yet"
        text="When the agent changes a file in “Ask me” or “Work on its own”, the turn is listed here with every file before and after, and you can undo it."
        className="m-auto h-full px-4"
      />
    );
  }
  const count = turn.files.length;
  const lines = file?.lines ?? [];
  const visible = lines.filter((l) =>
    side === "both" ? true : side === "before" ? l.t !== "add" : l.t !== "del",
  );
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div className="flex min-w-0 flex-wrap items-center gap-2 border-b px-3 py-2">
        <select
          aria-label="Which turn"
          value={turn.turn_id}
          onChange={(e) => {
            setTurnId(e.target.value);
            setPath(null);
          }}
          className="h-8 w-0 min-w-32 flex-1 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          {items.map((c) => (
            <option key={c.turn_id} value={c.turn_id}>
              Turn {c.position} · {c.request.split("\n")[0]?.slice(0, 60)}
              {timeOf(c.started_at) ? ` · ${timeOf(c.started_at)}` : ""}
              {c.undone ? " · undone" : ""}
            </option>
          ))}
        </select>
        {turn.undone ? (
          <Button
            size="sm"
            variant="outline"
            disabled={busy || working || !turn.can_redo}
            title={
              turn.can_redo
                ? undefined
                : "The files were changed since, or a later undo must come back first."
            }
            onClick={() => void put(false)}
          >
            <Redo2 /> Bring it back
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={busy || working || !turn.can_undo}
            title={
              working
                ? "Not while the agent is working."
                : turn.can_undo
                  ? undefined
                  : "Undo the later turns first: undo goes back one turn at a time."
            }
            onClick={() => void put(true)}
          >
            <Undo2 /> Undo this turn
          </Button>
        )}
      </div>
      {turn.undone ? (
        <div className="px-3 pt-3">
          <Notice tone="info" title={`Turn ${turn.position} is undone`}>
            {count === 1 ? "This file is" : `These ${count} files are`} back to how{" "}
            {count === 1 ? "it was" : "they were"} before the turn. Nothing is lost: “Bring it back”
            puts the turn's changes in again.
          </Notice>
        </div>
      ) : null}
      {note ? (
        <div className="px-3 pt-3">
          <Notice tone="warn" title="Also put back">
            {note}
          </Notice>
        </div>
      ) : null}
      {problem ? <p className="m-0 px-3 pt-2 text-sm text-destructive">{problem}</p> : null}
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(9rem,15rem)_minmax(0,1fr)]">
        <nav
          aria-label={`Files turn ${turn.position} changed`}
          className="min-h-0 overflow-auto border-e p-1.5"
        >
          <ul className="m-0 list-none p-0">
            {turn.files.map((f) => (
              <li key={f.path}>
                <button
                  type="button"
                  aria-current={shown === f.path ? "true" : undefined}
                  onClick={() => setPath(f.path)}
                  title={`${f.path} · ${WHAT[f.what]}`}
                  className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-start text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-[current=true]:bg-accent aria-[current=true]:font-medium"
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      "w-3 shrink-0 text-center font-mono text-xs",
                      f.what === "added" && "text-ok",
                      f.what === "deleted" && "text-destructive",
                    )}
                  >
                    {MARK[f.what]}
                  </span>
                  <span className={cn("truncate", turn.undone && "line-through opacity-70")}>
                    {f.path.split("/").pop()}
                  </span>
                  <span className="sr-only">{WHAT[f.what]}</span>
                  {f.test ? (
                    <span className="ms-auto shrink-0 rounded border px-1 text-2xs text-muted-foreground">
                      test
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex min-h-0 min-w-0 flex-col">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-1.5">
            <code className="truncate text-xs">
              {shown} <span className="text-muted-foreground">· {file ? WHAT[file.what] : ""}</span>
            </code>
            <Segmented
              size="sm"
              label="What to show"
              value={side}
              onValueChange={(v) => setSide(v as typeof side)}
              options={[
                { value: "before", label: "Before" },
                { value: "after", label: "After" },
                { value: "both", label: "Both" },
              ]}
            />
          </div>
          {!file ? (
            <div className="grid flex-1 place-items-center">
              <Spinner />
            </div>
          ) : file.binary || file.too_large ? (
            <EmptyState
              size="sm"
              icon={FileDiff}
              title={file.binary ? "This file is not text" : "This file is too long to show here"}
              text={`It was ${WHAT[file.what]} in this turn. Undo puts it back all the same.`}
              className="m-auto px-4"
            />
          ) : visible.length === 0 ? (
            <p className="m-0 p-4 text-sm text-muted-foreground">
              {side === "before"
                ? "The file did not exist before this turn."
                : side === "after"
                  ? "The file does not exist after this turn."
                  : "The file is empty."}
            </p>
          ) : (
            <pre
              // biome-ignore lint/a11y/noNoninteractiveTabindex: a long file is scrolled with the keyboard
              tabIndex={0}
              aria-label={`${shown}, ${side === "both" ? "before and after" : side}`}
              className="m-0 min-h-0 flex-1 overflow-auto p-0 text-xs leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <code className="grid grid-cols-[auto_auto_minmax(0,1fr)]">
                {visible.map((line, n) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: lines of a file are in order and never move
                  <span key={n} className="contents" data-line={line.t}>
                    <span
                      aria-hidden="true"
                      className="select-none border-e px-2 text-end text-muted-foreground"
                    >
                      {/* the number the line has where it is shown: after, unless it was removed */}
                      {(side === "before" || line.t === "del" ? line.a : line.b) ?? ""}
                    </span>
                    <span
                      className={cn(
                        "select-none px-1.5 text-center",
                        side === "both" && line.t === "add" && "bg-ok/15 text-ok",
                        side === "both" && line.t === "del" && "bg-destructive/15 text-destructive",
                      )}
                    >
                      {side !== "both" || line.t === "same" ? " " : line.t === "add" ? "+" : "−"}
                      <span className="sr-only">
                        {side !== "both" || line.t === "same"
                          ? ""
                          : line.t === "add"
                            ? "added: "
                            : "removed: "}
                      </span>
                    </span>
                    <span
                      className={cn(
                        "px-2 whitespace-pre",
                        side === "both" && line.t === "add" && "bg-ok/10",
                        side === "both" && line.t === "del" && "bg-destructive/10",
                      )}
                    >
                      {line.text || " "}
                    </span>
                  </span>
                ))}
              </code>
            </pre>
          )}
          <p className="m-0 flex items-start gap-1.5 border-t px-3 py-1.5 text-xs text-muted-foreground">
            <Info aria-hidden="true" className="mt-0.5 size-3 shrink-0" />
            <span>
              Undo puts back files that were changed, added or deleted, and where your own git
              stood. It does not put back files your project ignores (such as <code>.env</code>).
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}
