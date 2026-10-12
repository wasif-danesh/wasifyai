"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const POLL_MS = 10_000; // a clip or a transcript takes minutes: there is no need to ask faster
export const BURST_MS = 3_000; // right after one starts, until its row shows up
export const BURST_FOR_MS = 45_000;
export const TRANSCRIPT_STARTED_EVENT = "wasifyai:transcript-started";

type Item = { id: string; status: string; error?: string | null };

export type Outcome = { id: string; status: "done" | "failed"; prompt: string; error?: string };

export type ActivityConfig<T extends Item> = {
  product: string;
  collection: string; // the list route: /videos, /transcripts
  label: (item: T) => string; // what the notice calls the finished item
  startedEvent: string; // fired by the create page when it starts one
};

async function get<T>(product: string, path: string, signal: AbortSignal): Promise<T | null> {
  const res = await fetch(`/api/products/${product}${path}`, { signal });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(String(res.status));
  return (await res.json()) as T;
}

/**
 * What the site shows on every page while something is being made in the background (ADR-0037,
 * ADR-0043): the items that are working, and one notice when one finishes or fails. The server is the
 * source of truth: this only asks `GET /<collection>?status=working`, once on load, then every 10 seconds
 * while something is working and the tab is visible, and quickly for a short while after the create page
 * starts one.
 */
export function useWorkingActivity<T extends Item>(config: ActivityConfig<T>, enabled: boolean) {
  const [working, setWorking] = useState<T[]>([]);
  const [notice, setNotice] = useState<Outcome | null>(null);
  const known = useRef(new Map<string, string>()); // working item id -> what it is called
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const burstUntil = useRef(0);
  const stopped = useRef(false);
  const cfg = useRef(config);
  cfg.current = config;

  const dismiss = useCallback(() => setNotice(null), []);

  useEffect(() => {
    if (!enabled) return;
    stopped.current = false;
    const ctrl = new AbortController();
    const { product, collection, startedEvent } = cfg.current;

    const schedule = (ms: number) => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void check(), ms);
    };

    async function check() {
      if (stopped.current) return;
      if (document.hidden) return; // resumed by visibilitychange
      try {
        const page = await get<Record<string, T[]>>(
          product,
          `/${collection}?status=working&limit=5`,
          ctrl.signal,
        );
        if (page === null) {
          stopped.current = true; // not signed in: nothing to show
          return;
        }
        const items = page[collection] ?? [];
        const now = new Map(items.map((v) => [v.id, cfg.current.label(v)]));
        // one that was working and is not any more: say how it ended
        for (const [id, label] of known.current) {
          if (now.has(id)) continue;
          const v = await get<T>(product, `/${collection}/${id}`, ctrl.signal).catch(() => null);
          if (v && (v.status === "done" || v.status === "failed")) {
            setNotice({
              id,
              status: v.status,
              prompt: cfg.current.label(v) || label,
              error: v.error ?? undefined,
            });
          }
        }
        known.current = now;
        setWorking(items);
        const bursting = Date.now() < burstUntil.current;
        if (items.length > 0) schedule(POLL_MS);
        else if (bursting) schedule(BURST_MS);
      } catch {
        if (!ctrl.signal.aborted) schedule(POLL_MS * 2); // the service hiccuped: try again later
      }
    }

    const started = () => {
      burstUntil.current = Date.now() + BURST_FOR_MS;
      void check();
    };
    const visible = () => {
      if (!document.hidden) void check();
    };
    window.addEventListener(startedEvent, started);
    document.addEventListener("visibilitychange", visible);
    void check();
    return () => {
      stopped.current = true;
      ctrl.abort();
      if (timer.current) clearTimeout(timer.current);
      window.removeEventListener(startedEvent, started);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [enabled]);

  return { working, notice, dismiss };
}
