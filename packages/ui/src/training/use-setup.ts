"use client";

import type { TrainingApi, TrainingSetupState } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

const words = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/**
 * The trainer's component on a desktop engine: read while training is not ready, followed while it is being
 * set up, and `onReady` once it is (the screen then reads the training status again). Where the engine has no
 * such component (the web), the state stays null and nothing is offered.
 */
export function useTrainingSetup(
  api: TrainingApi,
  enabled: boolean,
  onReady: () => void,
  pollMs = 1500,
) {
  const [setup, setSetup] = useState<TrainingSetupState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const done = useRef(onReady);
  done.current = onReady;
  const was = useRef<string | null>(null);

  const read = useCallback(async () => {
    try {
      const s = await api.setup();
      setSetup(s);
      if (was.current === "installing" && s.progress.state === "ready") done.current();
      was.current = s.progress.state;
    } catch {
      setSetup(null); // no such component here: nothing to set up from this screen
    }
  }, [api]);

  useEffect(() => {
    if (enabled) void read();
  }, [enabled, read]);

  const installing = setup?.progress.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const timer = setInterval(() => void read(), pollMs);
    return () => clearInterval(timer);
  }, [installing, read, pollMs]);

  const install = useCallback(
    async (bytes: number) => {
      setError(null);
      try {
        const s = await api.installSetup(bytes);
        was.current = s.progress.state;
        setSetup(s);
      } catch (e) {
        setError(words(e, "Setting up could not be started."));
        await read();
      }
    },
    [api, read],
  );

  const cancel = useCallback(async () => {
    try {
      setSetup(await api.cancelSetup());
    } catch (e) {
      setError(words(e, "It could not be stopped."));
    }
  }, [api]);

  const remove = useCallback(async () => {
    setError(null);
    try {
      const r = await api.removeSetup();
      setSetup(r);
      done.current();
      return r.freed_bytes;
    } catch (e) {
      setError(words(e, "It could not be removed."));
      return 0;
    }
  }, [api]);

  return { setup, error, install, cancel, remove, reload: read };
}
