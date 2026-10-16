"use client";

import { type GuideState, type NotebooksApi, type RunClient, makeOutput } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

function describe(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/**
 * The guide to a notebook: read when the notebook opens and when its sources change, made once on
 * its own when there is none and a chat model is chosen, and made again on request when the
 * sources have changed since. It is saved with the notebook by the engine.
 */
export function useGuide(
  api: NotebooksApi,
  runs: Pick<RunClient, "startRun">,
  notebookId: string | null,
  opts: { canMake: boolean; readyCount: number; documentIds?: string[] },
) {
  const [state, setState] = useState<GuideState | null>(null);
  const [making, setMaking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const tried = useRef<string>("");
  const abort = useRef<AbortController | null>(null);

  const read = useCallback(async () => {
    if (!notebookId) return;
    try {
      setState(await api.guide(notebookId));
    } catch (e) {
      setProblem(describe(e, "The guide could not be read."));
    }
  }, [api, notebookId]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: read again when sources become ready
  useEffect(() => {
    setState(null);
    setProblem(null);
    if (notebookId) void read();
  }, [notebookId, opts.readyCount, read]);

  const make = useCallback(async () => {
    if (!notebookId || making) return;
    setProblem(null);
    setMaking(true);
    const ctrl = new AbortController();
    abort.current = ctrl;
    try {
      const out = await makeOutput(
        runs,
        { notebookId, format: "guide", prompt: "", documentIds: undefined },
        ctrl.signal,
      );
      if (!out.ok) setProblem(out.message);
    } catch (e) {
      if (!ctrl.signal.aborted) setProblem(describe(e, "The guide could not be made."));
    } finally {
      setMaking(false);
      await read();
    }
  }, [notebookId, making, runs, read]);

  // the first guide is made without being asked, once per notebook and set of sources
  useEffect(() => {
    if (!notebookId || !state || !opts.canMake || making) return;
    if (state.guide || !state.ready) return;
    const key = `${notebookId}:${opts.readyCount}`;
    if (tried.current === key) return;
    tried.current = key;
    void make();
  }, [notebookId, state, opts.canMake, opts.readyCount, making, make]);

  useEffect(() => () => abort.current?.abort(), []);

  return { state, making, problem, make };
}
