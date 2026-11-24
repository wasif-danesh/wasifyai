"use client";

// A menu group's one setup card (ADR-0109): opening any item of a group that is not set up shows it, and its one
// button sets up every part every item of the group needs, so no item of the group asks again. What the group needs
// comes from the engine (`SetupGroup`); the window runs the parts and reports the progress here.
import type { SetupGroup } from "@wasifyai/client";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { Bar } from "../components/progress-bar";
import { useMakingHere } from "../shell/making-here";
import { groupLabel, insteadLabel, partStatus, primaryLabel, usesLine, whyLine } from "./words";

export type SetupRun =
  | { state: "idle" }
  | { state: "running"; label: string; fraction: number | undefined }
  | { state: "failed"; message: string };

export type GroupSetupCardProps = {
  group: SetupGroup;
  /** the chat model's download, when the group needs chat and none is set up (the window's chat choice) */
  chatBytes?: number | null;
  run: SetupRun;
  /** download the group's parts; `instead`: also what the key would have done, under "Download instead" */
  onSetUp: (instead: boolean) => void;
  /** open the model button's Cloud tab, to add a key */
  onKey: () => void;
  onStop: () => void;
  /** where the person chooses another model or adds a key without setting the group up */
  onOther?: () => void;
};

export function GroupSetupCard({
  group,
  chatBytes = null,
  run,
  onSetUp,
  onKey,
  onStop,
  onOther,
}: GroupSetupCardProps) {
  const label = groupLabel(group.id);
  const instead = insteadLabel(group, chatBytes);
  const busy = run.state === "running";
  useMakingHere(busy ? `Setting up ${label}` : null);
  return (
    <section
      aria-label={`Set up ${label}`}
      className="mx-auto my-8 grid w-full min-w-0 max-w-xl gap-4 rounded-2xl border bg-card p-6"
    >
      <header className="grid gap-1">
        <h2 className="m-0 font-semibold text-xl">Get started with {label}</h2>
        <p className="m-0 text-muted-foreground text-sm">
          {whyLine(group)}
          {usesLine(group)}
        </p>
      </header>
      <ul className="m-0 grid list-none gap-1 p-0" aria-label="What it sets up">
        {group.parts.map((p) => (
          <li key={p.id} className="flex justify-between gap-3 text-sm">
            <span className="min-w-0">{p.title}</span>
            <span
              className={cn(
                "whitespace-nowrap tabular-nums",
                p.set_up ? "text-ok-strong" : "text-muted-foreground",
              )}
            >
              {partStatus(p, group.key.first, chatBytes)}
            </span>
          </li>
        ))}
      </ul>
      {busy ? (
        <div className="grid gap-2" aria-live="polite">
          <Bar value={run.fraction} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="m-0 text-muted-foreground text-sm">{run.label}</p>
            <Button type="button" variant="outline" size="sm" onClick={onStop}>
              Stop
            </Button>
          </div>
          <p className="m-0 text-muted-foreground text-xs">
            You can leave this screen; it carries on, and picks up where it stopped if the app
            closes.
          </p>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={() => (group.key.first ? onKey() : onSetUp(false))}>
            {primaryLabel(group, chatBytes)}
          </Button>
          {instead ? (
            <Button type="button" variant="outline" onClick={() => onSetUp(true)}>
              {instead}
            </Button>
          ) : null}
          {!group.key.first && group.key.covers ? (
            <Button type="button" variant="ghost" onClick={onKey}>
              Use an API key instead
            </Button>
          ) : null}
        </div>
      )}
      {run.state === "failed" ? (
        <Notice tone="error" title="It did not finish">
          {run.message} Press the button again to carry on from where it stopped.
        </Notice>
      ) : null}
      {onOther && !busy ? (
        <button
          type="button"
          className="justify-self-start text-primary text-sm underline"
          onClick={onOther}
        >
          Other choices
        </button>
      ) : null}
    </section>
  );
}
