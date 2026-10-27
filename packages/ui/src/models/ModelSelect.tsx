"use client";

import { ChevronDown, Download, Eye } from "lucide-react";
import { type Ref, useEffect, useId, useImperativeHandle, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Modal } from "../components/dialog";
import { Bar } from "../components/progress-bar";
import { formatBytes } from "../notebook/format";
import { useChoicesChanged } from "./context";
import { type ChoicesApi, type GroupId, type ModelChoice, groupOf } from "./types";
import { useModelChoices } from "./use-model-choices";

/** What a screen can ask of the picker: open the panel (when the person presses the main button with no model). */
export type ModelSelectHandle = {
  open(): void;
  /** Ask (the download dialog) about one model, for a card that offers it. */
  ask(id: string): void;
};

const FIT_ORDER = { fits: 0, tight: 1, too_big: 2 } as const;
const TIER_ORDER = { recommended: 0, also: 1, advanced: 2 } as const;
/** At most this many models are offered first (ADR-0086): a novice is not shown a list to study. */
export const FIRST_VIEW = 3;

/** The models to show first: recommended ones that fit this computer best come first. */
export function firstView(choices: ModelChoice[]): ModelChoice[] {
  const fitOf = (c: ModelChoice) => (c.fit ? FIT_ORDER[c.fit] : 0);
  return choices
    .filter((c) => c.tier !== "advanced")
    .sort(
      (a, b) =>
        Number(b.chosen) - Number(a.chosen) ||
        fitOf(a) - fitOf(b) ||
        TIER_ORDER[a.tier] - TIER_ORDER[b.tier],
    )
    .slice(0, FIRST_VIEW);
}

/** About how long a download takes on a typical connection (50 megabits a second), in words. */
export function timeText(bytes: number): string {
  const minutes = Math.max(1, Math.round(bytes / 6_250_000 / 60));
  return minutes === 1
    ? "about a minute"
    : minutes >= 90
      ? "over an hour"
      : `about ${minutes} minutes`;
}

export const COMMERCIAL: Record<ModelChoice["commercial"], string> = {
  yes: "Commercial use allowed",
  conditional: "Commercial use with conditions",
  no: "Not for commercial use",
  unreviewed: "Licence not reviewed",
};

function stateLine(c: ModelChoice): string {
  if (c.state === "ready") return c.chosen ? "In use" : "On this computer";
  if (c.state === "too_big") return "Too big for this computer";
  if (c.state === "unavailable") return c.unavailableReason ?? "Not available here";
  return `${formatBytes(c.downloadBytes + c.engineBytes)} to download`;
}

type Tab = "recommended" | "device" | "more";

/**
 * "Select image model": the same button and panel for every group (ADR-0086). Choosing a model that is on the
 * computer uses it; choosing one that is not opens a dialog that says what will be downloaded and, on a yes,
 * downloads it and uses it. The window supplies the rows and the work through `api`.
 */
export function ModelSelect({
  group,
  api,
  handleRef,
  disabled,
  onChanged,
  value,
  className,
}: {
  group: GroupId;
  api: ChoicesApi | null;
  handleRef?: Ref<ModelSelectHandle>;
  disabled?: boolean;
  /** the screen's own choice, when it keeps one: it is the one shown in use */
  value?: string | null;
  /** a model was chosen (the screen can reload what depends on it) */
  onChanged?: (id: string | null) => void;
  className?: string;
}) {
  const g = groupOf(group);
  const id = useId();
  const m = useModelChoices(api, group);
  const changed = useChoicesChanged();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("recommended");
  const [asking, setAsking] = useState<ModelChoice | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const rows = useRef<ModelChoice[]>([]);
  rows.current = m.list?.choices ?? [];
  useImperativeHandle(
    handleRef,
    () => ({
      open: () => setOpen(true),
      ask: (id) => {
        const c = rows.current.find((x) => x.id === id);
        if (c) setAsking(c);
      },
    }),
    [],
  );

  // opening starts on what suits: the model in use is shown first; with nothing on the computer, the recommended ones
  const choices = (m.list?.choices ?? []).map((c) =>
    value === undefined ? c : { ...c, chosen: c.id === value && c.state === "ready" },
  );
  const chosen = choices.find((c) => c.chosen) ?? null;
  const onDevice = choices.filter((c) => c.state === "ready");
  // only when the panel opens
  // biome-ignore lint/correctness/useExhaustiveDependencies: the tab is chosen once per opening
  useEffect(() => {
    if (open) {
      void m.reload();
      setTab(onDevice.length > 0 ? "device" : "recommended");
    }
  }, [open]);

  const shown =
    tab === "recommended"
      ? firstView(choices)
      : tab === "device"
        ? onDevice
        : choices.filter((c) => c.tier === "advanced");

  const getting = m.working;
  const label = chosen?.title ?? g.select;

  async function pick(c: ModelChoice) {
    if (c.state === "ready") {
      await m.choose(c.id);
      onChanged?.(c.id);
      changed();
      setOpen(false);
    } else if (c.state === "needs_download") {
      setAsking(c);
    }
  }

  // the download goes on in the background (the tray shows it): the dialog and the panel close at once
  function download(c: ModelChoice) {
    const started = m.get(c.id, () => {
      onChanged?.(c.id);
      changed();
    });
    if (!started) return;
    setAsking(null);
    setOpen(false);
  }

  return (
    <div ref={root} className={cn("relative inline-block max-w-full min-w-0", className)}>
      <Button
        type="button"
        variant="outline"
        className="max-w-full"
        disabled={disabled || !api}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="min-w-0 max-w-[16rem] truncate">{label}</span>
        {getting ? (
          <span className="text-muted-foreground text-xs">
            {getting.progress.fraction === null
              ? "Downloading…"
              : `Downloading ${Math.round(getting.progress.fraction * 100)}%`}
          </span>
        ) : chosen ? null : (
          <span className="sr-only"> (no model chosen)</span>
        )}
        <ChevronDown className="size-4" aria-hidden="true" />
      </Button>

      {open ? (
        // a dialog in the middle of the window (stage U3 of the UI plan), never a panel over the form
        <Modal label={g.select} onClose={() => setOpen(false)}>
          <div
            id={`${id}-panel`}
            className="grid max-h-[70vh] grid-cols-[minmax(0,1fr)] content-start gap-3 overflow-y-auto"
          >
            <div
              role="tablist"
              aria-label="Models"
              className="flex gap-1 rounded-full border p-1 text-sm"
            >
              {(
                [
                  ["recommended", "Recommended"],
                  ["device", "On this computer"],
                  ...(api?.more || choices.some((c) => c.tier === "advanced")
                    ? [["more", "More"]]
                    : []),
                ] as [Tab, string][]
              ).map(([key, text]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  className={cn(
                    "flex-1 rounded-full px-3 py-1.5",
                    tab === key ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent",
                  )}
                  onClick={() => setTab(key)}
                >
                  {text}
                </button>
              ))}
            </div>

            {m.error ? (
              <p role="alert" className="text-destructive text-sm">
                {m.error}
              </p>
            ) : null}
            {m.problem ? (
              <p role="alert" className="text-destructive text-sm">
                {m.problem}
              </p>
            ) : null}

            {!m.list && !m.error ? <p className="text-muted-foreground text-sm">Looking…</p> : null}
            {m.list && shown.length === 0 && tab !== "more" ? (
              <p className="text-muted-foreground text-sm">
                {tab === "device"
                  ? "Nothing is on this computer yet. Choose one under Recommended."
                  : "No models for this yet."}
              </p>
            ) : null}

            <ul
              className="m-0 grid list-none gap-1 p-0"
              aria-label={tab === "device" ? "On this computer" : "Models"}
            >
              {shown.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    disabled={c.state === "too_big" || c.state === "unavailable"}
                    aria-current={c.chosen ? "true" : undefined}
                    className={cn(
                      "grid w-full grid-cols-[minmax(0,1fr)] gap-0.5 rounded-lg px-3 py-2 text-start outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 disabled:hover:bg-transparent",
                      c.chosen && "bg-accent",
                    )}
                    onClick={() => void pick(c)}
                  >
                    <span className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate font-medium text-sm" title={c.title}>
                        {c.title}
                      </span>
                      {c.readsPictures ? (
                        <span title="Can read pictures" className="text-muted-foreground">
                          <Eye className="size-3.5" aria-label="Can read pictures" />
                        </span>
                      ) : null}
                      {c.tier === "recommended" ? (
                        <span className="rounded-full border px-2 py-0.5 text-xs">Recommended</span>
                      ) : null}
                    </span>
                    <span className="text-muted-foreground text-sm [overflow-wrap:anywhere]">
                      {c.plain}
                    </span>
                    <span
                      className={cn(
                        "flex items-center gap-1.5 text-xs",
                        c.state === "ready" ? "text-ok" : "text-muted-foreground",
                      )}
                    >
                      {c.state === "needs_download" ? (
                        <Download className="size-3" aria-hidden="true" />
                      ) : null}
                      {stateLine(c)}
                      {c.fit === "tight" ? " · may be slow here" : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>

            {tab === "more" && api?.more ? <div className="grid gap-2">{api.more}</div> : null}
          </div>
        </Modal>
      ) : null}

      {asking ? (
        <GetModelDialog
          choice={asking}
          diskFree={m.list?.diskFreeBytes ?? null}
          working={getting?.id === asking.id ? getting.progress : null}
          problem={m.problem}
          onGet={() => download(asking)}
          onCancel={() => setAsking(null)}
        />
      ) : null}
    </div>
  );
}

/** "To use this we need to download it": in words, with what will be fetched, the licence and whether it fits. */
export function GetModelDialog({
  place = "device",
  choice,
  diskFree,
  working,
  problem,
  onGet,
  onCancel,
}: {
  /** where the files go: this computer, or a worker of the service (the web, for an admin) */
  place?: "device" | "service";
  choice: ModelChoice;
  diskFree: number | null;
  working: { label: string; fraction: number | null } | null;
  problem: string | null;
  onGet: () => void;
  onCancel: () => void;
}) {
  const total = choice.downloadBytes + choice.engineBytes;
  const tooLittleDisk = diskFree !== null && diskFree < total + 1e9;
  return (
    <Modal label={`Download ${choice.title}?`} onClose={onCancel}>
      <div className="grid gap-3 text-sm">
        <p className="m-0">
          To use <strong>{choice.title}</strong> we need to download it first. {choice.plain}
        </p>
        <ul className="m-0 grid list-none gap-1 p-0">
          {choice.engineBytes > 0 ? (
            <li className="flex justify-between gap-4">
              <span>{choice.engineName ?? "The engine"} (once)</span>
              <span>{formatBytes(choice.engineBytes)}</span>
            </li>
          ) : null}
          <li className="flex justify-between gap-4">
            <span>{choice.title}</span>
            <span>{formatBytes(choice.downloadBytes)}</span>
          </li>
          <li className="flex justify-between gap-4 border-t pt-1 font-medium">
            <span>Total</span>
            <span>
              {formatBytes(total)}, {timeText(total)}
            </span>
          </li>
        </ul>
        <p className="m-0 text-muted-foreground">
          {choice.from ? `It is downloaded from ${choice.from}. ` : ""}
          {place === "service"
            ? "It is downloaded onto the worker and runs there, for everyone who uses this service. "
            : "It runs on this computer; nothing you make is sent away. "}
          {COMMERCIAL[choice.commercial]}
          {choice.licenceUrl ? (
            <>
              {" "}
              (
              <a
                className="underline underline-offset-4"
                href={choice.licenceUrl}
                target="_blank"
                rel="noreferrer"
              >
                licence
              </a>
              )
            </>
          ) : null}
          .
        </p>
        <p className="m-0 text-muted-foreground">
          It downloads in the background: you can keep using the app and see how far it is at the
          top right.
        </p>
        {choice.fit === "tight" ? (
          <p className="m-0 text-warn">
            {choice.fitReason ?? "This computer is tight on memory for it."}
          </p>
        ) : null}
        {tooLittleDisk ? (
          <p role="alert" className="m-0 text-destructive">
            There is not enough free disk space: {formatBytes(diskFree ?? 0)} free,{" "}
            {formatBytes(total)} needed.
          </p>
        ) : null}
        {problem ? (
          <p role="alert" className="m-0 text-destructive">
            {problem}
          </p>
        ) : null}
        {working ? (
          <div className="grid gap-2" aria-live="polite">
            <Bar value={working.fraction ?? undefined} />
            <span className="text-muted-foreground">
              {working.label}
              {working.fraction !== null ? `, ${Math.round(working.fraction * 100)}%` : ""}
            </span>
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          {working ? "Stop" : "Not now"}
        </Button>
        <Button
          type="button"
          onClick={onGet}
          disabled={Boolean(working) || tooLittleDisk}
          autoFocus
        >
          {problem ? "Try again" : place === "service" ? "Get on the worker" : "Download and use"}
        </Button>
      </div>
    </Modal>
  );
}
