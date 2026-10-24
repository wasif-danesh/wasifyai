"use client";

import { type ImageResult, flowReducer, initialState, isResting } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { IMAGE_PRODUCT, type ImageFlowApi } from "../hooks/use-image-flow";

export type TryItState =
  | { phase: "idle" }
  | { phase: "drawing"; step: 1 | 2; without?: ImageResult }
  | { phase: "done"; without: ImageResult; with: ImageResult }
  | { phase: "failed"; message: string };

const RECONNECTS = 4;

/** One picture, from the request to the result: the run's events are folded as the image screen does. */
export async function drawOne(
  runs: ImageFlowApi,
  input: object,
  signal: AbortSignal,
): Promise<ImageResult> {
  let state = initialState;
  const onEvent = (event: Parameters<Parameters<ImageFlowApi["startRun"]>[3]>[0]) => {
    state = flowReducer(state, { type: "event", event });
  };
  await runs.startRun(IMAGE_PRODUCT, input, signal, onEvent);
  // the stream can end while the run is still going: look again, a few times
  for (let attempt = 0; attempt < RECONNECTS && !isResting(state) && state.runId; attempt++) {
    await runs.watchRun(state.runId, state.lastSeq, signal, onEvent);
  }
  if (state.phase === "done" && state.result) return state.result;
  if (state.refusal) throw new Error(state.refusal.message);
  throw new Error(state.error?.message ?? "The picture could not be made.");
}

/**
 * Draw one prompt twice with the same seed: without the model's style, then with it. The image
 * engine holds one job at a time, so the two pictures are made one after the other.
 */
export function useTryIt(runs: ImageFlowApi | undefined) {
  const [state, setState] = useState<TryItState>({ phase: "idle" });
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  const draw = useCallback(
    async (prompt: string, style: string, weight = 1) => {
      if (!runs) return;
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      const seed = Math.floor(Math.random() * 2_000_000_000);
      const base = { mode: "text", prompt, size: "square", seed };
      try {
        setState({ phase: "drawing", step: 1 });
        const without = await drawOne(runs, base, ctrl.signal);
        setState({ phase: "drawing", step: 2, without });
        const withStyle = await drawOne(
          runs,
          { ...base, loras: [{ name: style, weight }] },
          ctrl.signal,
        );
        setState({ phase: "done", without, with: withStyle });
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setState({
          phase: "failed",
          message: e instanceof Error ? e.message : "The pictures could not be made.",
        });
      }
    },
    [runs],
  );

  return { state, draw, reset: () => setState({ phase: "idle" }) };
}
