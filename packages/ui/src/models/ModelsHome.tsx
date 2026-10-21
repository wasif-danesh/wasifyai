"use client";

import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Button } from "../components/button";
import { Modal } from "../components/dialog";
import { formatBytes } from "../notebook/format";
import { ModelSelect } from "./ModelSelect";
import { useChoicesFor, useChoicesVersion } from "./context";
import { type ChoiceList, GROUPS, type GroupId, type ModelChoice, groupOf } from "./types";
import { useModelChoices } from "./use-model-choices";

/** A model off the computer, with the question first: in words, how much space it frees, and that it can be got again. */
function RemoveDialog({
  choice,
  working,
  problem,
  onRemove,
  onCancel,
}: {
  choice: ModelChoice;
  working: boolean;
  problem: string | null;
  onRemove: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal label={`Remove ${choice.title}?`} onClose={onCancel}>
      <div className="grid gap-3 text-sm">
        <p className="m-0">
          Remove <strong>{choice.title}</strong> from this computer
          {choice.sizeBytes ? `? This frees ${formatBytes(choice.sizeBytes)}` : "?"}. You can get it
          again later.
        </p>
        {problem ? (
          <p role="alert" className="m-0 text-destructive">
            {problem}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>
            Not now
          </Button>
          <Button type="button" disabled={working} onClick={onRemove}>
            {working ? "Removing…" : "Remove"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** One group on the Models page: what it is for, the model in use, the picker, and what can be taken off. */
function GroupCard({ group }: { group: GroupId }) {
  const g = groupOf(group);
  const api = useChoicesFor(group);
  const m = useModelChoices(api);
  const version = useChoicesVersion();
  const [removing, setRemoving] = useState<ModelChoice | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    void m.reload();
  }, [version]);

  const ready = (m.list?.choices ?? []).filter((c) => c.state === "ready");
  const inUse = ready.find((c) => c.chosen) ?? null;
  const status = !m.list
    ? "Looking…"
    : inUse
      ? `In use: ${inUse.title}`
      : ready.length > 0
        ? `${ready.length} on this computer`
        : "Nothing downloaded yet";

  async function remove(c: ModelChoice) {
    if (!api?.remove) return;
    setBusy(true);
    setProblem(null);
    try {
      await api.remove(c.id);
      setRemoving(null);
      await m.reload();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be removed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label={g.title}
      className="grid content-start gap-3 rounded-2xl border bg-card p-5"
    >
      <div>
        <h2 className="m-0 font-semibold text-lg">{g.title}</h2>
        <p className="m-0 text-muted-foreground text-sm">{g.about}</p>
      </div>
      <p className="m-0 text-sm" data-testid={`status-${group}`}>
        {status}
      </p>
      <ModelSelect group={group} api={api} />
      {ready.length > 0 ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">
            On this computer ({ready.length})
          </summary>
          <ul className="m-0 mt-2 grid list-none gap-1 p-0">
            {ready.map((c) => (
              <li key={c.id} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate">{c.title}</span>
                {c.sizeBytes ? (
                  <span className="text-muted-foreground text-xs">{formatBytes(c.sizeBytes)}</span>
                ) : null}
                {c.removable && api?.remove ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    aria-label={`Remove ${c.title}`}
                    onClick={() => {
                      setProblem(null);
                      setRemoving(c);
                    }}
                  >
                    Remove
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {removing ? (
        <RemoveDialog
          choice={removing}
          working={busy}
          problem={problem}
          onRemove={() => void remove(removing)}
          onCancel={() => setRemoving(null)}
        />
      ) : null}
    </section>
  );
}

/** Memory and disk of this computer, from any group's list. */
function useMachine(): ChoiceList | null {
  const api = useChoicesFor("chat");
  const version = useChoicesVersion();
  const [list, setList] = useState<ChoiceList | null>(null);
  const load = useCallback(() => {
    api
      ?.list()
      .then(setList)
      .catch(() => {});
  }, [api]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(load, [load, version]);
  return list;
}

/**
 * The Models page (ADR-0086): one card for each group, named for what a person wants to do, with the model in use
 * and the same picker as everywhere. What only an expert needs (model folders, files other tools left, Hugging Face)
 * goes in `advanced`.
 */
export function ModelsHome({
  advanced,
  advancedOpen = false,
}: {
  advanced?: ReactNode;
  advancedOpen?: boolean;
}) {
  const machine = useMachine();
  return (
    <div className="grid gap-6">
      <header className="grid gap-1">
        <h1 className="m-0 font-semibold text-2xl">Models</h1>
        <p className="m-0 text-muted-foreground">
          Pick what Wasify AI uses for each job. Everything runs on this computer.
        </p>
        {machine && (machine.memoryBytes !== null || machine.diskFreeBytes !== null) ? (
          <p className="m-0 text-muted-foreground text-sm" data-testid="machine">
            This computer:{" "}
            {[
              machine.memoryBytes !== null ? `${formatBytes(machine.memoryBytes)} of memory` : null,
              machine.diskFreeBytes !== null ? `${formatBytes(machine.diskFreeBytes)} free` : null,
            ]
              .filter(Boolean)
              .join(", ")}
            .
          </p>
        ) : null}
      </header>
      <div className="grid gap-4 md:grid-cols-2">
        {GROUPS.map((g) => (
          <GroupCard key={g.id} group={g.id} />
        ))}
      </div>
      {advanced ? (
        <details className="rounded-2xl border p-5" open={advancedOpen || undefined}>
          <summary className="cursor-pointer font-medium">Advanced</summary>
          <div className="mt-4 grid gap-8">{advanced}</div>
        </details>
      ) : null}
    </div>
  );
}
