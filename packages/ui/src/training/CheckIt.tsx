"use client";

import type { TrainedModel, TrainingApi } from "@wasifyai/client";
import { Check, Loader2, Minus, X } from "lucide-react";
import { useEffect } from "react";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import type { ImageFlowApi } from "../hooks/use-image-flow";
import { actions, hint } from "../styles";
import { useCheck } from "./use-check";

/** The mark on a model: what the check found, in words, or that it has not been made. */
export function EvaluationLine({ model }: { model: TrainedModel }) {
  const ev = model.card.evaluation;
  if (model.preview) return null;
  if (!ev || ev.passed === null) {
    return (
      <p className={hint}>
        {ev?.note && ev.note !== "Not evaluated yet." ? ev.note : "Not checked yet."}
      </p>
    );
  }
  return (
    <p className="m-0 text-sm">
      <span
        className={
          ev.passed
            ? "rounded-full border border-emerald-600/40 px-2 py-0.5 text-emerald-700 text-xs dark:text-emerald-400"
            : "rounded-full border border-amber-600/40 px-2 py-0.5 text-amber-700 text-xs dark:text-amber-400"
        }
      >
        {ev.passed ? "Passed" : "Did not pass"}
      </span>{" "}
      <span className="text-muted-foreground">{ev.note}</span>
    </p>
  );
}

/**
 * "Did it learn?": draws the model with and without what it was taught and says whether the pictures look like the
 * ones it learnt from. Runs by itself once, when `auto` is set (right after a run); the button runs it again.
 */
export function CheckIt({
  model,
  api,
  runs,
  auto = false,
  onSaved,
}: {
  model: TrainedModel;
  api: TrainingApi;
  runs: ImageFlowApi;
  auto?: boolean;
  onSaved: (m: TrainedModel) => void;
}) {
  const { state, start } = useCheck(api, runs, model, onSaved);
  const evaluated = Boolean(model.card.evaluation?.at);
  // by itself, once: while nothing has been checked and nothing is going. (Not a "has asked" flag: a screen that mounts,
  // unmounts and mounts again would stop the first check and never start the second.)
  useEffect(() => {
    if (
      auto &&
      state.phase === "idle" &&
      !evaluated &&
      !model.preview &&
      model.card.published?.lora_name
    ) {
      void start();
    }
  }, [auto, state.phase, evaluated, model.preview, model.card.published, start]);
  if (model.preview || !model.card.published?.lora_name) return null;
  const working = state.phase === "working";
  const shown = state.phase === "working" || state.phase === "done" ? state.shown : [];
  return (
    <section className="grid gap-3" aria-label={`Check ${model.name}`}>
      <h3 className="m-0 font-semibold">Did it learn?</h3>
      <p className={hint}>
        It draws two new scenes three ways: with {model.name} and its magic word, with {model.name}{" "}
        but without the word, and without {model.name}. A model that reads pictures then says which
        ones look like yours.
      </p>
      <div className={actions}>
        <Button type="button" variant="outline" disabled={working} onClick={() => void start()}>
          {working ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
          {working
            ? `Checking, ${state.done} of ${state.total} drawn…`
            : state.phase === "done" || model.card.evaluation.at
              ? "Check again"
              : "Check it"}
        </Button>
      </div>
      {state.phase === "failed" ? (
        <Notice tone="error" title="The check could not be made">
          {state.message}
        </Notice>
      ) : null}
      {shown.length > 0 ? (
        <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0 md:grid-cols-3">
          {shown.map((s) => (
            <li key={s.id} className="grid gap-1">
              <img
                src={s.url}
                alt={`${s.label}: ${s.prompt}`}
                className="aspect-square w-full rounded-lg border object-cover"
              />
              <span className="flex items-center gap-1 text-xs">
                {s.same === null ? (
                  <Minus className="size-3.5 text-muted-foreground" aria-label="Not judged" />
                ) : s.same ? (
                  <Check className="size-3.5 text-emerald-600" aria-label="Looks like yours" />
                ) : (
                  <X
                    className="size-3.5 text-muted-foreground"
                    aria-label="Does not look like yours"
                  />
                )}
                {s.label}
              </span>
              {s.reason ? (
                <span className="line-clamp-3 text-muted-foreground text-xs" title={s.reason}>
                  {s.reason}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {state.phase === "done" ? <EvaluationLine model={state.model} /> : null}
    </section>
  );
}
