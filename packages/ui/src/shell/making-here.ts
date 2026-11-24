"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * What a screen of this window is making right now ("Making your picture…"). The top bar's tray lists the
 * engine's jobs, but a picture, a song or a lip sync video started on its own screen is a run, not a job, so
 * the tray said "Idle" while the screen said "Making…" (the screen review of 2026-11-20). A screen showing
 * its working state puts it here while it shows it; the tray reads it with the jobs.
 */
type Entry = { id: string; label: string };

let entries: Entry[] = [];
const listeners = new Set<() => void>();
let next = 0;

function emit() {
  for (const l of listeners) l();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Says `label` is being made here while the calling component is shown; nothing when `label` is empty. */
export function useMakingHere(label: string | null | undefined) {
  useEffect(() => {
    if (!label) return;
    next += 1;
    const id = `here-${next}`;
    entries = [...entries, { id, label }];
    emit();
    return () => {
      entries = entries.filter((e) => e.id !== id);
      emit();
    };
  }, [label]);
}

/** Everything being made on this window's screens now. */
export function useMadeHereNow(): Entry[] {
  return useSyncExternalStore(
    subscribe,
    () => entries,
    () => entries,
  );
}

/** A screen's entry is left out when a job already says it ("Making your video: …" for "Making your video…"). */
export function withoutListed(here: Entry[], listed: { label: string }[]): Entry[] {
  const stem = (s: string) =>
    s
      .replace(/[…。.]+$/u, "")
      .trim()
      .toLowerCase();
  return here.filter((h) => !listed.some((j) => stem(j.label).startsWith(stem(h.label))));
}
