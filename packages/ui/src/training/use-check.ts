"use client";

import type { CheckedPicture, TrainedModel, TrainingApi } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ImageFlowApi } from "../hooks/use-image-flow";
import { drawOne } from "./use-try-it";

/** One picture of the check as the screen shows it. */
export type CheckShown = CheckedPicture & { url: string; label: string };

export type CheckState =
  | { phase: "idle" }
  | { phase: "working"; done: number; total: number; shown: CheckShown[] }
  | { phase: "done"; shown: CheckShown[]; model: TrainedModel }
  | { phase: "failed"; message: string };

const LABEL: Record<CheckedPicture["condition"], string> = {
  with_word: "With the model and its magic word",
  without_word: "With the model, without the magic word",
  without_model: "Without the model",
};

const words = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/**
 * "Did it learn?" (ADR-0073 decision 10): draw the pictures the engine plans, each scene with the model and its magic
 * word, with the model alone and without the model, and ask the picture-reading model whether each looks like the
 * pictures it learnt from. The pictures are shown as they come; the engine puts the sentence and the mark on the
 * model's card. A model that reads no pictures leaves the pictures there and the verdict open.
 */
export function useCheck(
  api: TrainingApi,
  runs: ImageFlowApi | undefined,
  model: TrainedModel,
  onSaved: (m: TrainedModel) => void,
) {
  const [state, setState] = useState<CheckState>({ phase: "idle" });
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  const start = useCallback(async () => {
    const style = model.card.published?.lora_name;
    if (!runs || !style) return;
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    const shown: CheckShown[] = [];
    try {
      const { items: plan } = await api.checkPlan(model.id);
      const seed = Math.floor(Math.random() * 2_000_000_000);
      let canJudge = true;
      for (const step of plan) {
        setState({ phase: "working", done: shown.length, total: plan.length, shown: [...shown] });
        const input = {
          mode: "text",
          prompt: step.prompt,
          size: "square",
          seed: seed + step.scene, // the same scene is drawn from one seed in all three ways
          ...(step.with_model ? { loras: [{ name: style, weight: 1 }] } : {}),
        };
        const image = await drawOne(runs, input, ctrl.signal);
        let same: boolean | null = null;
        let reason = "";
        if (canJudge) {
          try {
            const blob = await (await fetch(image.imageUrl)).blob();
            ({ same, reason } = await api.judge(model.id, blob));
          } catch (e) {
            canJudge = false; // no picture-reading model: draw the rest, judge none
            reason = words(e, "It could not be judged.");
          }
        }
        shown.push({
          id: step.id,
          condition: step.condition,
          prompt: step.prompt,
          same,
          reason,
          url: image.imageUrl,
          label: LABEL[step.condition],
        });
      }
      const saved = await api.saveEvaluation(
        model.id,
        shown.map(({ id, condition, prompt, same, reason }) => ({
          id,
          condition,
          prompt,
          same,
          reason,
        })),
      );
      setState({ phase: "done", shown, model: saved });
      onSaved(saved);
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setState({ phase: "failed", message: words(e, "The check could not be made.") });
    }
  }, [api, runs, model, onSaved]);

  return { state, start };
}
