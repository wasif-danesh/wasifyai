"use client";

import { Check, Download, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../components/button";
import { Bar } from "../components/progress-bar";
import type { ChoicesApi, GetProgress, GroupId } from "./types";

export type DownloadStatus = "queued" | "running" | "done" | "failed";

/** One model being fetched: a row of the tray. */
export type DownloadRow = {
  key: string;
  group: GroupId;
  id: string;
  title: string;
  status: DownloadStatus;
  progress: GetProgress;
  error: string | null;
};

type Request = {
  group: GroupId;
  id: string;
  title: string;
  api: ChoicesApi;
  /** the model is there and chosen: the screen that asked reads its rows again */
  onDone?: () => void;
};

type Job = Request & { key: string; ctrl: AbortController };

/** Done rows go away by themselves; a failed one stays until the person closes it. */
const DONE_MS = 6000;
const keyOf = (group: GroupId, id: string) => `${group}:${id}`;

/**
 * Model downloads that do not block the window (ADR-0086 amendment). A download is started from a dialog that closes at once; it runs here, one
 * at a time in the order asked, whichever screen is open, and the tray shows how far it is. `bump` tells every screen that the models changed.
 */
export function useDownloadManager(bump: () => void) {
  const [items, setItems] = useState<DownloadRow[]>([]);
  const queue = useRef<Job[]>([]);
  const running = useRef<string | null>(null);
  const requests = useRef(new Map<string, Request>()); // what a row was asked with, so "Try again" can ask again
  const controllers = useRef(new Map<string, AbortController>());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const bumpRef = useRef(bump);
  bumpRef.current = bump;

  const patch = useCallback((key: string, change: Partial<DownloadRow>) => {
    setItems((all) => all.map((d) => (d.key === key ? { ...d, ...change } : d)));
  }, []);

  const dismiss = useCallback((key: string) => {
    const t = timers.current.get(key);
    if (t) clearTimeout(t);
    timers.current.delete(key);
    requests.current.delete(key);
    controllers.current.delete(key);
    setItems((all) => all.filter((d) => d.key !== key));
  }, []);

  const pump = useCallback(async () => {
    if (running.current) return;
    const job = queue.current.shift();
    if (!job) return;
    running.current = job.key;
    patch(job.key, { status: "running", progress: { label: "Starting", fraction: null } });
    try {
      await job.api.get(job.id, (progress) => patch(job.key, { progress }), job.ctrl.signal);
      patch(job.key, { status: "done", progress: { label: "Ready", fraction: 1 } });
      job.onDone?.();
      bumpRef.current();
      timers.current.set(
        job.key,
        setTimeout(() => dismiss(job.key), DONE_MS),
      );
    } catch (e) {
      if (job.ctrl.signal.aborted) dismiss(job.key);
      else {
        patch(job.key, {
          status: "failed",
          error: e instanceof Error ? e.message : "That could not be downloaded.",
        });
      }
    } finally {
      running.current = null;
      controllers.current.delete(job.key);
      void pump();
    }
  }, [patch, dismiss]);

  const start = useCallback(
    (req: Request): boolean => {
      const key = keyOf(req.group, req.id);
      if (queue.current.some((j) => j.key === key) || running.current === key) return true; // already on its way
      const ctrl = new AbortController();
      requests.current.set(key, req);
      controllers.current.set(key, ctrl);
      queue.current.push({ ...req, key, ctrl });
      const row: DownloadRow = {
        key,
        group: req.group,
        id: req.id,
        title: req.title,
        status: "queued",
        progress: { label: "Waiting", fraction: null },
        error: null,
      };
      // an earlier failed or finished row of the same model is replaced
      setItems((all) => [...all.filter((d) => d.key !== key), row]);
      void pump();
      return true;
    },
    [pump],
  );

  const cancel = useCallback(
    (key: string) => {
      const waiting = queue.current.findIndex((j) => j.key === key);
      if (waiting >= 0) {
        queue.current.splice(waiting, 1);
        dismiss(key);
      } else controllers.current.get(key)?.abort(); // the running one: its adapter stops, and `pump` closes the row
    },
    [dismiss],
  );

  const retry = useCallback(
    (key: string) => {
      const req = requests.current.get(key);
      if (req) start(req);
    },
    [start],
  );

  useEffect(() => {
    const open = timers.current;
    return () => {
      for (const t of open.values()) clearTimeout(t);
    };
  }, []);

  return useMemo(
    () => ({ items, start, cancel, dismiss, retry }),
    [items, start, cancel, dismiss, retry],
  );
}

export type DownloadManager = ReturnType<typeof useDownloadManager>;

/** The rows of the tray: what is coming, what is coming now, what is ready, what failed. */
export function DownloadTray({ manager }: { manager: DownloadManager }) {
  const { items, cancel, dismiss, retry } = manager;
  if (items.length === 0) return null;
  const active = items.filter((d) => d.status === "running" || d.status === "queued").length;
  return (
    <section
      aria-label="Downloads"
      className="fixed end-4 top-14 z-50 grid w-[min(22rem,calc(100vw-2rem))] gap-1.5 rounded-xl border bg-background p-2 shadow-card"
    >
      <h2 className="m-0 flex items-center gap-2 px-1 font-medium text-sm">
        <Download className="size-4 text-primary" aria-hidden="true" />
        {active > 0 ? "Download in progress" : "Downloads"}
        {active > 1 ? <span className="text-muted-foreground">· {active}</span> : null}
      </h2>
      <ul className="m-0 grid list-none gap-1.5 p-0">
        {items.map((d) => (
          <li key={d.key} className="grid gap-1.5 rounded-lg bg-muted/50 px-2.5 py-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-medium" title={d.title}>
                {d.title}
              </span>
              {d.status === "done" ? (
                <span className="flex items-center gap-1 text-ok">
                  <Check className="size-4" aria-hidden="true" /> Ready
                </span>
              ) : d.status === "queued" ? (
                <span className="text-muted-foreground">Waiting</span>
              ) : d.status === "running" ? (
                <span className="tabular-nums text-muted-foreground">
                  {d.progress.fraction === null ? "…" : `${Math.round(d.progress.fraction * 100)}%`}
                </span>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7 shrink-0"
                aria-label={
                  d.status === "running" || d.status === "queued"
                    ? `Stop downloading ${d.title}`
                    : `Close ${d.title}`
                }
                onClick={() =>
                  d.status === "running" || d.status === "queued" ? cancel(d.key) : dismiss(d.key)
                }
              >
                <X className="size-4" aria-hidden="true" />
              </Button>
            </div>
            {d.status === "running" ? (
              <>
                <Bar value={d.progress.fraction ?? undefined} />
                <span className="truncate text-muted-foreground text-xs">{d.progress.label}</span>
              </>
            ) : null}
            {d.status === "failed" ? (
              <div className="flex items-center gap-2">
                <p role="alert" className="m-0 min-w-0 flex-1 text-destructive text-xs">
                  {d.error}
                </p>
                <Button type="button" variant="outline" size="sm" onClick={() => retry(d.key)}>
                  <RotateCcw className="size-3.5" aria-hidden="true" /> Try again
                </Button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="sr-only" aria-live="polite">
        {items
          .filter((d) => d.status === "done")
          .map((d) => `${d.title} is ready.`)
          .join(" ")}
      </p>
    </section>
  );
}
