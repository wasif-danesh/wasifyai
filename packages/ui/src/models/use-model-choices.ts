"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChoiceList, ChoicesApi, GetProgress } from "./types";

export type Working = { id: string; progress: GetProgress };

/**
 * The rows of one group, which one is chosen, and the two things a person does with a row: choose it (when it is
 * ready) or get it (when it is not). A "get" runs here so that it carries on if the panel is closed.
 */
export function useModelChoices(api: ChoicesApi | null) {
  const [list, setList] = useState<ChoiceList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState<Working | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    if (!api) return;
    try {
      setList(await api.list());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The models could not be listed.");
    }
  }, [api]);

  useEffect(() => {
    void reload();
  }, [reload]);

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

  const get = useCallback(
    async (id: string): Promise<boolean> => {
      if (!api || working) return false;
      const ctrl = new AbortController();
      abort.current = ctrl;
      setProblem(null);
      setWorking({ id, progress: { label: "Starting", fraction: null } });
      try {
        await api.get(id, (progress) => setWorking({ id, progress }), ctrl.signal);
        return true;
      } catch (e) {
        if (!ctrl.signal.aborted) {
          setProblem(e instanceof Error ? e.message : "That could not be downloaded.");
        }
        return false;
      } finally {
        abort.current = null;
        setWorking(null);
        await reload();
      }
    },
    [api, working, reload],
  );

  const cancel = useCallback(() => abort.current?.abort(), []);

  const chosen = list?.choices.find((c) => c.chosen) ?? null;
  return { list, chosen, error, working, problem, setProblem, choose, get, cancel, reload };
}
