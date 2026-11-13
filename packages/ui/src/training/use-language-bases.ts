"use client";

import type { LanguageBase, TrainingApi } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

const words = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/**
 * The bases a writing model can be taught on (ADR-0074): what of each is on this computer, and getting the rest, one
 * part at a time (its weights, or the chat form of it) after the size was shown. Read again while anything is being
 * downloaded, and `onChange` when something arrived.
 */
export function useLanguageBases(api: TrainingApi, pollMs = 1500, onChange?: () => void) {
  const [bases, setBases] = useState<LanguageBase[]>([]);
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

  const take = useCallback((next: LanguageBase[]) => {
    if (!alive.current) return;
    setBases(next);
    // something arrived: tell the screen (it reads its own status again)
    const have = next.map((b) => `${b.id}:${b.model.have}:${b.chat.have}`).join(",");
    if (was.current && was.current !== have) changed.current?.();
    was.current = have;
  }, []);

  const read = useCallback(async () => {
    try {
      take(await api.languageBases());
    } catch {
      /* no language component here: nothing to offer */
    }
  }, [api, take]);

  useEffect(() => {
    void read();
  }, [read]);

  const busy = bases.some(
    (b) => b.model.progress.state === "installing" || b.chat.progress.state === "installing",
  );
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void read(), pollMs);
    return () => clearInterval(timer);
  }, [busy, read, pollMs]);

  const install = useCallback(
    async (baseId: string, part: "model" | "chat", bytes: number) => {
      setError(null);
      try {
        take(await api.installLanguagePart(baseId, part, bytes));
      } catch (e) {
        setError(words(e, "The download could not be started."));
        await read();
      }
    },
    [api, take, read],
  );

  const cancel = useCallback(
    async (baseId: string, part: "model" | "chat") => {
      try {
        take(await api.cancelLanguagePart(baseId, part));
      } catch (e) {
        setError(words(e, "It could not be stopped."));
      }
    },
    [api, take],
  );

  return { bases, error, install, cancel, reload: read };
}
