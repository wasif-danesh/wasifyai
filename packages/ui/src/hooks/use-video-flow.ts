"use client";

import {
  HttpError,
  type ParsedEvent,
  type RunClient,
  type VideoFlowAction,
  type VideoFlowState,
  type VideoMode,
  initialVideoState,
  isVideoResting,
  videoFlowReducer,
} from "@wasifyai/client";
import { useCallback, useEffect, useReducer, useRef } from "react";

export const VIDEO_PRODUCT = "wasifyai-video";
const STORAGE_KEY = "wasifyai-video:run";
const MAX_RECONNECTS = 6;

/** What the flow needs from the app's client: start a run and re-attach to one. */
export type VideoFlowApi = Pick<RunClient, "startRun" | "watchRun">;

/**
 * `imageKey` is the key of a picture already uploaded (ADR-0039); text to video has none. `sourceId` is the
 * clip of the person's library to carry on (Extend video), which has no picture and no shape.
 */
export type VideoRequest = {
  mode: VideoMode;
  prompt: string;
  /** a shape name (text to video only: a clip made from a picture keeps the picture's shape) */
  shape?: string;
  seconds: number;
  imageKey?: string;
  sourceId?: string;
  /** looks the person taught (LoRAs on the video model), each with its strength */
  loras?: { name: string; weight: number }[];
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
 * Drives one video from request to result: starts the run, folds its events into `state` with a pure
 * reducer, reconnects when the connection drops and re-attaches to a run after a page reload.
 */
export function useVideoFlow(api: VideoFlowApi) {
  const { startRun, watchRun } = api;
  const [state, dispatchRaw] = useReducer(videoFlowReducer, initialVideoState);
  const local = useRef<VideoFlowState>(initialVideoState);
  const abort = useRef<AbortController | null>(null);
  const lastRequest = useRef<VideoRequest | null>(null);

  const dispatch = useCallback((action: VideoFlowAction) => {
    local.current = videoFlowReducer(local.current, action);
    dispatchRaw(action);
  }, []);

  const onEvent = useCallback(
    (event: ParsedEvent) => {
      dispatch({ type: "event", event });
      const { phase, runId } = local.current;
      // Only a run that is still going is worth re-attaching to; a finished video is in Your videos.
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
        if (signal.aborted || isVideoResting(local.current)) return;
        const runId = local.current.runId;
        if (!runId || attempt >= MAX_RECONNECTS) {
          dispatch({
            type: "failed",
            message: "We lost the connection to your video. Reload to pick it up again.",
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
    (request: VideoRequest) => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      lastRequest.current = request;
      remember(null);
      if (request.mode === "image" && !request.imageKey) {
        dispatch({ type: "failed", message: "Please choose a picture.", retryable: false });
        return;
      }
      if (request.mode === "extend" && !request.sourceId) {
        dispatch({ type: "failed", message: "Please choose a video.", retryable: false });
        return;
      }
      dispatch({ type: "submitted" });
      const input =
        request.mode === "extend"
          ? {
              mode: "extend",
              prompt: request.prompt,
              source_id: request.sourceId,
              seconds: request.seconds,
            }
          : {
              mode: request.mode,
              prompt: request.prompt,
              seconds: request.seconds,
              ...(request.mode === "text"
                ? { shape: request.shape }
                : { image_key: request.imageKey }),
            };
      const body =
        request.loras && request.loras.length > 0 ? { ...input, loras: request.loras } : input;
      void follow((signal) => startRun(VIDEO_PRODUCT, body, signal, onEvent), ctrl.signal);
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
