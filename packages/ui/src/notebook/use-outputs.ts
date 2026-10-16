"use client";

import {
  type MakeResult,
  type NotebookOutput,
  type NotebooksApi,
  type RunClient,
  type StudioFormat,
  makeOutput,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { making } from "./outputs";

const POLL_MS = 2000;

function describe(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/**
 * The outputs of one notebook, read again every 2 s while any is being made (the engine saves an
 * output whether or not this screen stayed open), and a way to start one.
 */
export function useOutputs(
  api: NotebooksApi,
  runs: Pick<RunClient, "startRun">,
  notebookId: string | null,
) {
  const [outputs, setOutputs] = useState<NotebookOutput[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [step, setStep] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const id = useRef(notebookId);
  id.current = notebookId;

  const refresh = useCallback(async () => {
    const nid = id.current;
    if (!nid) return;
    try {
      setOutputs(await api.outputs(nid));
    } catch (e) {
      setProblem(describe(e, "The outputs could not be read."));
    }
  }, [api]);

  useEffect(() => {
    setOutputs([]);
    if (notebookId) void refresh();
  }, [notebookId, refresh]);

  const anyMaking = outputs.some(making);
  useEffect(() => {
    if (!anyMaking || !notebookId) return;
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [anyMaking, notebookId, refresh]);

  useEffect(() => () => abort.current?.abort(), []);

  const make = useCallback(
    async (
      format: StudioFormat,
      prompt: string,
      documentIds?: string[],
    ): Promise<MakeResult | null> => {
      const nid = id.current;
      if (!nid) return null;
      setProblem(null);
      setStarting(true);
      const ctrl = new AbortController();
      abort.current = ctrl;
      // the output row appears as soon as the engine has made it, so look for it while it runs
      const timer = setInterval(() => void refresh(), 1000);
      try {
        const out = await makeOutput(
          runs,
          { notebookId: nid, format, prompt, documentIds },
          ctrl.signal,
          setStep,
        );
        if (!out.ok) setProblem(out.message);
        return out;
      } catch (e) {
        if (!ctrl.signal.aborted) setProblem(describe(e, "That could not be started."));
        return null;
      } finally {
        clearInterval(timer);
        setStarting(false);
        setStep(null);
        await refresh();
      }
    },
    [refresh, runs],
  );

  return {
    outputs,
    problem,
    step,
    busy: starting || anyMaking,
    clearProblem: () => setProblem(null),
    refresh,
    make,
    rename: async (oid: string, title: string) => {
      if (!id.current) return;
      try {
        await api.renameOutput(id.current, oid, title);
      } catch (e) {
        setProblem(describe(e, "The name could not be changed."));
      }
      await refresh();
    },
    remove: async (oid: string) => {
      if (!id.current) return;
      try {
        await api.removeOutput(id.current, oid);
      } catch (e) {
        setProblem(describe(e, "It could not be deleted."));
      }
      await refresh();
    },
    stop: async (oid: string) => {
      if (!id.current) return;
      try {
        await api.cancelOutput(id.current, oid);
      } catch (e) {
        setProblem(describe(e, "It could not be stopped."));
      }
      await refresh();
    },
  };
}
