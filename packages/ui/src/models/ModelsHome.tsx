"use client";

import { type KeyboardEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Modal } from "../components/dialog";
import { formatBytes } from "../notebook/format";
import { COMMERCIAL, GetModelDialog } from "./ModelSelect";
import { useChoicesChanged, useChoicesFor, useChoicesVersion } from "./context";
import { GROUPS, type GroupId, type ModelChoice } from "./types";
import { useModelChoices } from "./use-model-choices";

type Place = "device" | "service";

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

const TIER = { recommended: 0, also: 1, advanced: 2 } as const;

/** In use first, then what is here, then the recommended ones, then the rest. */
export function tableOrder(choices: ModelChoice[]): ModelChoice[] {
  const rank = (c: ModelChoice) =>
    c.chosen ? 0 : c.state === "ready" ? 1 : c.state === "needs_download" ? 2 : 3;
  return [...choices].sort((a, b) => rank(a) - rank(b) || TIER[a.tier] - TIER[b.tier]);
}

function statusOf(
  c: ModelChoice,
  place: Place,
): { text: string; tone: "ok" | "use" | "plain" | "warn" } {
  const here = place === "service" ? "On the worker" : "On this computer";
  if (c.state === "ready")
    return c.chosen ? { text: "In use", tone: "use" } : { text: here, tone: "ok" };
  if (c.state === "too_big") return { text: "Won't fit here", tone: "warn" };
  if (c.state === "unavailable")
    return { text: c.unavailableReason ?? "Not available here", tone: "warn" };
  return { text: place === "service" ? "Not on the worker" : "Not downloaded", tone: "plain" };
}

const TONE: Record<string, string> = {
  ok: "bg-ok/10 text-foreground",
  use: "bg-accent text-accent-foreground",
  plain: "bg-muted text-muted-foreground",
  warn: "bg-warn/10 text-foreground",
};

function sizeText(c: ModelChoice): string {
  if (c.state === "ready") return c.sizeBytes ? formatBytes(c.sizeBytes) : "—";
  const total = c.downloadBytes + c.engineBytes;
  return total > 0 ? formatBytes(total) : "—";
}

/** One tab: the models of a group as a table, with the one thing a person can do to each. */
function GroupTable({ group, place }: { group: GroupId; place: Place }) {
  const api = useChoicesFor(group);
  const m = useModelChoices(api);
  const version = useChoicesVersion();
  const changed = useChoicesChanged();
  const [asking, setAsking] = useState<ModelChoice | null>(null);
  const [removing, setRemoving] = useState<ModelChoice | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    void m.reload();
  }, [version]);

  const rows = useMemo(() => tableOrder(m.list?.choices ?? []), [m.list]);

  async function use(c: ModelChoice) {
    await m.choose(c.id);
    changed();
  }

  async function get(c: ModelChoice) {
    if (!(await m.get(c.id))) return;
    changed();
    setAsking(null);
  }

  async function remove(c: ModelChoice) {
    if (!api?.remove) return;
    setBusy(true);
    setProblem(null);
    try {
      await api.remove(c.id);
      setRemoving(null);
      await m.reload();
      changed();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be removed.");
    } finally {
      setBusy(false);
    }
  }

  const head = "px-4 py-2 text-start font-medium text-muted-foreground text-xs";
  return (
    <div className="grid gap-2">
      {m.error ? (
        <p role="alert" className="m-0 px-4 text-destructive text-sm">
          {m.error}
        </p>
      ) : null}
      {m.problem && !asking ? (
        <p role="alert" className="m-0 px-4 text-destructive text-sm">
          {m.problem}
        </p>
      ) : null}
      {!m.list && !m.error ? (
        <p className="m-0 px-4 text-muted-foreground text-sm">Looking…</p>
      ) : null}
      {m.list && rows.length === 0 ? (
        <p className="m-0 px-4 text-muted-foreground text-sm">No models for this yet.</p>
      ) : null}
      {rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">{groupLabel(group)} models</caption>
            <thead>
              <tr className="border-b">
                <th scope="col" className={head}>
                  Model
                </th>
                <th scope="col" className={head}>
                  Size
                </th>
                <th scope="col" className={head}>
                  Licence
                </th>
                <th scope="col" className={head}>
                  {place === "service" ? "On the worker" : "Status"}
                </th>
                <th scope="col" className={head}>
                  <span className="sr-only">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const s = statusOf(c, place);
                return (
                  <tr key={c.id} className="border-b last:border-b-0 align-top">
                    <th scope="row" className="px-4 py-3 text-start font-normal">
                      <div className="font-medium">
                        {c.title}
                        {c.tier === "recommended" ? (
                          <span className="ms-2 font-normal text-accent-foreground text-xs">
                            Recommended
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-0.5 max-w-prose text-muted-foreground text-xs">
                        {c.plain}
                      </div>
                    </th>
                    <td className="whitespace-nowrap px-4 py-3">{sizeText(c)}</td>
                    <td className="px-4 py-3">
                      <div>{c.licence}</div>
                      {c.commercial !== "yes" ? (
                        <div className="mt-0.5 text-muted-foreground text-xs">
                          {COMMERCIAL[c.commercial]}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn("rounded-md px-2 py-0.5 text-xs", TONE[s.tone])}>
                        {s.text}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-end">
                      {c.state === "ready" && !c.chosen ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          aria-label={`Use ${c.title}`}
                          onClick={() => void use(c)}
                        >
                          Use
                        </Button>
                      ) : null}
                      {c.state === "needs_download" ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          aria-label={`Get ${c.title}`}
                          onClick={() => {
                            m.setProblem(null);
                            setAsking(c);
                          }}
                        >
                          Get
                        </Button>
                      ) : null}
                      {c.state === "ready" && c.removable && api?.remove ? (
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
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {asking ? (
        <GetModelDialog
          place={place}
          choice={asking}
          diskFree={m.list?.diskFreeBytes ?? null}
          working={m.working?.id === asking.id ? m.working.progress : null}
          problem={m.problem}
          onGet={() => void get(asking)}
          onCancel={() => {
            if (m.working) m.cancel();
            setAsking(null);
          }}
        />
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
    </div>
  );
}

const groupLabel = (id: GroupId) => GROUPS.find((g) => g.id === id)?.title ?? id;

/**
 * The Models page: one tab for each group, named for what a person wants to do, and under it a table of the models with
 * their size, licence and state and one action each (ADR-0089; it replaces the cards of ADR-0086). Groups with no picker
 * in this app (the web serves only some) have no tab. What only an expert needs (model folders, files other tools left,
 * Hugging Face) goes in `advanced`, under the table.
 */
export function ModelsHome({
  advanced,
  advancedOpen = false,
  place = "device",
  initialGroup,
}: {
  advanced?: ReactNode;
  advancedOpen?: boolean;
  /** where the models are: this computer, or the workers of a service (the web, for an admin) */
  place?: Place;
  initialGroup?: GroupId;
}) {
  // one hook per group, always in the same order: a group the app has no picker for gets no tab
  const apis = GROUPS.map((g) => useChoicesFor(g.id));
  const tabs = GROUPS.filter((_, i) => apis[i] !== null);
  const first =
    initialGroup && tabs.some((g) => g.id === initialGroup) ? initialGroup : tabs[0]?.id;
  const [group, setGroup] = useState<GroupId | undefined>(first);
  const current = tabs.some((g) => g.id === group) ? group : tabs[0]?.id;
  const machine = useMachineLine(current);

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const i = tabs.findIndex((g) => g.id === current);
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (next === null || tabs.length === 0) return;
    e.preventDefault();
    const target = tabs[(next + tabs.length) % tabs.length];
    if (target) {
      setGroup(target.id);
      document.getElementById(`models-tab-${target.id}`)?.focus();
    }
  }

  return (
    <div className="grid gap-6">
      <header className="grid gap-1">
        <h1 className="m-0 font-semibold text-2xl">Models</h1>
        <p className="m-0 text-muted-foreground">
          {place === "service"
            ? "The models on this service's workers. Getting one puts it on the worker for everyone."
            : "Pick what Wasify AI uses for each job. Everything runs on this computer."}
        </p>
        {machine ? (
          <p className="m-0 text-muted-foreground text-sm" data-testid="machine">
            This computer: {machine}.
          </p>
        ) : null}
      </header>
      {tabs.length === 0 ? (
        <p className="m-0 text-muted-foreground">There are no models to manage here.</p>
      ) : (
        <div className="rounded-2xl border bg-card">
          <div
            role="tablist"
            aria-label="Kinds of model"
            className="flex gap-0.5 overflow-x-auto border-b px-3"
            onKeyDown={onKey}
          >
            {tabs.map((g) => (
              <button
                key={g.id}
                id={`models-tab-${g.id}`}
                type="button"
                role="tab"
                aria-selected={g.id === current}
                aria-controls="models-panel"
                tabIndex={g.id === current ? 0 : -1}
                className={cn(
                  "whitespace-nowrap border-b-2 px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  g.id === current
                    ? "border-primary font-medium"
                    : "border-transparent text-muted-foreground hover:bg-accent",
                )}
                onClick={() => setGroup(g.id)}
              >
                {g.title}
              </button>
            ))}
          </div>
          <div
            id="models-panel"
            role="tabpanel"
            aria-labelledby={current ? `models-tab-${current}` : undefined}
            className="py-2"
          >
            {current ? <GroupTable key={current} group={current} place={place} /> : null}
          </div>
        </div>
      )}
      {advanced ? (
        <details className="rounded-2xl border p-5" open={advancedOpen || undefined}>
          <summary className="cursor-pointer font-medium">Advanced</summary>
          <div className="mt-4 grid gap-8">{advanced}</div>
        </details>
      ) : null}
    </div>
  );
}

/** Memory and disk of this computer, from the list of the tab that is open. */
function useMachineLine(group: GroupId | undefined): string | null {
  const api = useChoicesFor(group ?? "chat");
  const version = useChoicesVersion();
  const [line, setLine] = useState<string | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    if (!api || !group) return setLine(null);
    api
      .list()
      .then((l) => {
        const parts = [
          l.memoryBytes !== null ? `${formatBytes(l.memoryBytes)} of memory` : null,
          l.diskFreeBytes !== null ? `${formatBytes(l.diskFreeBytes)} free` : null,
        ].filter(Boolean);
        setLine(parts.length > 0 ? parts.join(", ") : null);
      })
      .catch(() => setLine(null));
  }, [api, group, version]);
  return line;
}
