"use client";

import type { DecisionBase, TrainingApi } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

const words = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/**
 * The models a decision model can be taught on (ADR-0075): what of each is on this computer, and getting the rest after
 * the size was shown. Read again while anything is being downloaded, and `onChange` when something arrived.
 */
export function useDecisionBases(api: TrainingApi, pollMs = 1500, onChange?: () => void) {
  const [bases, setBases] = useState<DecisionBase[]>([]);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const changed = useRef(onChange);
  changed.current = onChange;
  const was = useRef("");

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const take = useCallback((next: DecisionBase[]) => {
    if (!alive.current) return;
    setBases(next);
    // something arrived: tell the screen (it reads its own status again)
    const have = next.map((b) => `${b.id}:${b.model.have}`).join(",");
    if (was.current && was.current !== have) changed.current?.();
    was.current = have;
  }, []);

  const read = useCallback(async () => {
    try {
      take(await api.decisionBases());
    } catch {
      /* no decision component here: nothing to offer */
    }
  }, [api, take]);

  useEffect(() => {
    void read();
  }, [read]);

  const busy = bases.some((b) => b.model.progress.state === "installing");
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void read(), pollMs);
    return () => clearInterval(timer);
  }, [busy, read, pollMs]);

  const install = useCallback(
    async (baseId: string, bytes: number) => {
      setError(null);
      try {
        take(await api.installDecisionBase(baseId, bytes));
      } catch (e) {
        setError(words(e, "The download could not be started."));
        await read();
      }
    },
    [api, take, read],
  );

  const cancel = useCallback(
    async (baseId: string) => {
      try {
        take(await api.cancelDecisionBase(baseId));
      } catch (e) {
        setError(words(e, "It could not be stopped."));
      }
    },
    [api, take],
  );

  return { bases, error, install, cancel, reload: read };
}
