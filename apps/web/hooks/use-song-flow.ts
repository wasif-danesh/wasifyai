"use client";

import {
  type Approval,
  HttpError,
  type SongInput,
  resumeRun,
  startRun,
  watchRun,
} from "@/lib/run-client";
import {
  type FlowAction,
  type FlowState,
  flowReducer,
  initialState,
  isResting,
} from "@/lib/song-flow";
import type { ParsedEvent } from "@/lib/sse";
import { useCallback, useEffect, useReducer, useRef } from "react";

const STORAGE_KEY = "wasifyai-music:run";
const MAX_RECONNECTS = 6;

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
 * Drives one song from idea to result. Events are folded into `state` by a pure reducer;
 * this hook only does the I/O: starting and answering runs, reconnecting when the connection
 * drops, and re-attaching to a run after a page reload.
 */
export function useSongFlow() {
  const [state, dispatchRaw] = useReducer(flowReducer, initialState);
  // The reducer's latest result, readable synchronously by the async control flow below.
  const local = useRef<FlowState>(initialState);
  const abort = useRef<AbortController | null>(null);
  const lastInput = useRef<SongInput | null>(null);

  const dispatch = useCallback((action: FlowAction) => {
    local.current = flowReducer(local.current, action);
    dispatchRaw(action);
  }, []);

  const onEvent = useCallback(
    (event: ParsedEvent) => {
      dispatch({ type: "event", event });
      const { phase, runId } = local.current;
      // Only a run that is still going (or waiting for the user) is worth re-attaching to after
      // a reload. A finished one lives in My creations; Create should open on an empty form.
      if (phase === "done" || phase === "refused" || phase === "error") remember(null);
      else if (runId) remember(runId);
    },
    [dispatch],
  );

  /** Run a stream; if it ends while the run is still going, reconnect and keep following it. */
  const follow = useCallback(
    async (open: (signal: AbortSignal) => Promise<void>) => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      const { signal } = ctrl;

      let attempt = 0;
      let step = open;
      for (;;) {
        try {
          await step(signal);
        } catch (e) {
          if (signal.aborted) return;
          // No run id yet means the request never started: report it instead of retrying blindly.
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
            message: "We lost the connection to your song. Reload to pick it up again.",
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
    (input: SongInput) => {
      lastInput.current = input;
      remember(null);
      dispatch({ type: "submitted" });
      void follow((signal) => startRun(input, signal, onEvent));
    },
    [dispatch, follow, onEvent],
  );

  const answer = useCallback(
    (value: Approval) => {
      const runId = local.current.runId;
      if (!runId) return;
      dispatch({ type: "answered" });
      void follow((signal) => resumeRun(runId, value, signal, onEvent));
    },
    [dispatch, follow, onEvent],
  );

  const reset = useCallback(() => {
    abort.current?.abort();
    remember(null);
    lastInput.current = null;
    dispatch({ type: "reset" });
  }, [dispatch]);

  const retry = useCallback(() => {
    if (lastInput.current) start(lastInput.current);
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
      dispatch({ type: "restoring" });
      void follow((signal) => watchRun(id, 0, signal, onEvent)).then(() => {
        // A run that no longer exists (expired) is not an error worth showing.
        if (local.current.phase === "error" && !local.current.runId) {
          remember(null);
          dispatch({ type: "reset" });
        }
      });
    }
    return () => abort.current?.abort();
  }, [dispatch, follow, onEvent]);

  return { state, start, answer, reset, retry };
}
