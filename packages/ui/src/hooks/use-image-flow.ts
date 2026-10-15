"use client";

import {
  type FlowAction,
  type FlowState,
  HttpError,
  type Mode,
  type ParsedEvent,
  type RunClient,
  flowReducer,
  initialState,
  isResting,
} from "@wasifyai/client";
import { useCallback, useEffect, useReducer, useRef } from "react";

export const IMAGE_PRODUCT = "wasifyai-image";
const STORAGE_KEY = "wasifyai-image:run";
const MAX_RECONNECTS = 6;

/** What the flow needs from the app's client: start a run and re-attach to one. */
export type ImageFlowApi = Pick<RunClient, "startRun" | "watchRun">;

/** `imageKey` is the key of a picture already uploaded (ADR-0039); text to image has none. */
export type ImageRequest = {
  mode: Mode;
  prompt: string;
  size?: string;
  imageKey?: string;
  /** Make the same picture again: the seed a recipe kept (text to image only). */
  seed?: number;
};

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
 * Drives one image from request to result: starts the run, folds its events into `state` with a pure reducer, reconnects when the connection drops and
 * re-attaches to a run after a page reload.
 */
export function useImageFlow(api: ImageFlowApi) {
  const { startRun, watchRun } = api;
  const [state, dispatchRaw] = useReducer(flowReducer, initialState);
  const local = useRef<FlowState>(initialState);
  const abort = useRef<AbortController | null>(null);
  const lastRequest = useRef<ImageRequest | null>(null);

  const dispatch = useCallback((action: FlowAction) => {
    local.current = flowReducer(local.current, action);
    dispatchRaw(action);
  }, []);

  const onEvent = useCallback(
    (event: ParsedEvent) => {
      dispatch({ type: "event", event });
      const { phase, runId } = local.current;
      // Only a run that is still going is worth re-attaching to; a finished image is in My creations.
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
            message: "We lost the connection to your image. Reload to pick it up again.",
          });
          return;
        }
        attempt += 1;
        await sleep(Math.min(500 * 2 ** attempt, 5000), signal);
        step = (s) => watchRun(runId, local.current.lastSeq, s, onEvent);
      }
    },
    [dispatch, onEvent, watchRun],
  );

  const start = useCallback(
    (request: ImageRequest) => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      lastRequest.current = request;
      remember(null);
      if (request.mode === "image" && !request.imageKey) {
        dispatch({ type: "failed", message: "Please choose a picture.", retryable: false });
        return;
      }
      dispatch({ type: "submitted" });
      const input = {
        mode: request.mode,
        prompt: request.prompt,
        ...(request.mode === "text"
          ? { size: request.size, ...(request.seed !== undefined ? { seed: request.seed } : {}) }
          : { image_key: request.imageKey }),
      };
      void follow((signal) => startRun(IMAGE_PRODUCT, input, signal, onEvent), ctrl.signal);
    },
    [dispatch, follow, onEvent, startRun],
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
  }, [dispatch, follow, onEvent, watchRun]);

  return { state, start, reset, retry };
}
