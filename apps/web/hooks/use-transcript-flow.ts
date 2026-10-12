"use client";

import { HttpError, startRun, watchRun } from "@/lib/run-client";
import type { ParsedEvent } from "@/lib/sse";
import {
  type FlowAction,
  type FlowState,
  flowReducer,
  initialState,
  isResting,
} from "@/lib/transcript-flow";
import { useCallback, useEffect, useReducer, useRef } from "react";

export const TRANSCRIBE_PRODUCT = "wasifyai-stt";
const STORAGE_KEY = "wasifyai-stt:run";
const MAX_RECONNECTS = 6;

/** `audioKey` is the key of a recording already uploaded; `language` is a code, or "auto" to detect it. */
export type TranscribeRequest = { audioKey: string; language: string };

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        resolve();
      },
      { once: true },
    );
  });

function remember(runId: string | null) {
  try {
    if (runId) sessionStorage.setItem(STORAGE_KEY, runId);
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage can be unavailable (private mode); the page still works, it just cannot restore
  }
}

function describe(e: unknown): string {
  if (e instanceof HttpError) return e.message;
  return "We couldn't reach the server. Check your connection and try again.";
}

/**
 * Drives one transcription from request to the moment it is being made (or done): starts the run, folds
 * its events into `state` with a pure reducer, reconnects when the connection drops and re-attaches to a
 * run after a page reload.
 */
export function useTranscriptFlow() {
  const [state, dispatchRaw] = useReducer(flowReducer, initialState);
  const local = useRef<FlowState>(initialState);
  const abort = useRef<AbortController | null>(null);
  const lastRequest = useRef<TranscribeRequest | null>(null);

  const dispatch = useCallback((action: FlowAction) => {
    local.current = flowReducer(local.current, action);
    dispatchRaw(action);
  }, []);

  const onEvent = useCallback(
    (event: ParsedEvent) => {
      dispatch({ type: "event", event });
      const { phase, runId } = local.current;
      // Only a run that is still going is worth re-attaching to; a finished clip is in My creations.
      if (phase === "done" || phase === "refused" || phase === "error") remember(null);
      else if (runId) remember(runId);
    },
    [dispatch],
  );

  /** Run a stream; if it ends while the run is still going, reconnect and keep following it. */
  const follow = useCallback(
    async (open: (signal: AbortSignal) => Promise<void>, signal: AbortSignal) => {
      let attempt = 0;
      let step = open;
      for (;;) {
        try {
          await step(signal);
        } catch (e) {
          if (signal.aborted) return;
          if (!local.current.runId || e instanceof HttpError) {
            dispatch({
              type: "failed",
              message: describe(e),
              retryable: !(e instanceof HttpError && e.status === 404),
            });
            return;
          }
        }
        if (signal.aborted || isResting(local.current)) return;
        const runId = local.current.runId;
        if (!runId || attempt >= MAX_RECONNECTS) {
          dispatch({
            type: "failed",
            message:
              "We lost the connection to your transcript. It may still be made: check My creations.",
          });
          return;
        }
        attempt += 1;
        await sleep(Math.min(500 * 2 ** attempt, 5000), signal);
        step = (s) => watchRun(runId, local.current.lastSeq, s, onEvent);
      }
    },
    [dispatch, onEvent],
  );

  const start = useCallback(
    (request: TranscribeRequest) => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      lastRequest.current = request;
      remember(null);
      if (!request.audioKey) {
        dispatch({ type: "failed", message: "Please add a recording first.", retryable: false });
        return;
      }
      dispatch({ type: "submitted" });
      const input = { audio_key: request.audioKey, language: request.language || "auto" };
      void follow((signal) => startRun(input, signal, onEvent, TRANSCRIBE_PRODUCT), ctrl.signal);
    },
    [dispatch, follow, onEvent],
  );

  const reset = useCallback(() => {
    abort.current?.abort();
    remember(null);
    lastRequest.current = null;
    dispatch({ type: "reset" });
  }, [dispatch]);

  const retry = useCallback(() => {
    if (lastRequest.current) start(lastRequest.current);
    else reset();
  }, [start, reset]);

  // After a reload, re-attach to the run we were watching: the server replays it from the start.
  useEffect(() => {
    let runId: string | null = null;
    try {
      runId = sessionStorage.getItem(STORAGE_KEY);
    } catch {
      // see remember()
    }
    if (runId) {
      const id = runId;
      const ctrl = new AbortController();
      abort.current = ctrl;
      dispatch({ type: "restoring" });
      void follow((signal) => watchRun(id, 0, signal, onEvent), ctrl.signal).then(() => {
        // A run that no longer exists (expired) is not an error worth showing.
        if (local.current.phase === "error" && !local.current.runId) {
          remember(null);
          dispatch({ type: "reset" });
        }
      });
    }
    return () => abort.current?.abort();
  }, [dispatch, follow, onEvent]);

  return { state, start, reset, retry };
}
