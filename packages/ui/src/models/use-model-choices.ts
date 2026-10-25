"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useChoicesVersion, useDownloadsContext } from "./context";
import { useDownloadManager } from "./downloads";
import type { ChoiceList, ChoicesApi, GetProgress, GroupId } from "./types";

export type Working = { id: string; progress: GetProgress };

/**
 * The rows of one group, which one is chosen, and the two things a person does with a row: choose it (when it is
 * ready) or get it (when it is not). **A "get" runs in the background** (ADR-0086 amendment): it is handed to the
 * downloads of the whole window, so it carries on when the dialog or the screen is gone, and the tray shows it.
 */
export function useModelChoices(api: ChoicesApi | null, group: GroupId) {
  const [list, setList] = useState<ChoiceList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const shared = useDownloadsContext();
  const own = useDownloadManager(() => {}); // only used where there is no provider (a small test)
  const downloads = shared ?? own;
  const version = useChoicesVersion();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    if (!api) return;
    try {
      const next = await api.list();
      if (!mounted.current) return;
      setList(next);
      setError(null);
    } catch (e) {
      if (mounted.current)
        setError(e instanceof Error ? e.message : "The models could not be listed.");
    }
  }, [api]);

  // read again when the models changed anywhere: a download finished, or another screen chose one
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    void reload();
  }, [reload, version]);

  const choose = useCallback(
    async (id: string) => {
      if (!api) return;
      setProblem(null);
      try {
        await api.choose(id);
      } catch (e) {
        setProblem(e instanceof Error ? e.message : "That model could not be used.");
      }
      await reload();
    },
    [api, reload],
  );

  const mine = downloads.items.find(
    (d) => d.group === group && (d.status === "running" || d.status === "queued"),
  );
  const working: Working | null = mine ? { id: mine.id, progress: mine.progress } : null;

  /** Start getting a model: it goes on in the background. `onDone` runs when it is there and chosen. */
  const get = useCallback(
    (id: string, onDone?: () => void): boolean => {
      if (!api) return false;
      setProblem(null);
      const title = list?.choices.find((c) => c.id === id)?.title ?? id;
      return downloads.start({
        group,
        id,
        title,
        api,
        onDone: () => {
          onDone?.();
          void reload();
        },
      });
    },
    [api, downloads, group, list, reload],
  );

  const cancel = useCallback(() => {
    if (mine) downloads.cancel(mine.key);
  }, [downloads, mine]);

  const chosen = list?.choices.find((c) => c.chosen) ?? null;
  return { list, chosen, error, working, problem, setProblem, choose, get, cancel, reload };
}
