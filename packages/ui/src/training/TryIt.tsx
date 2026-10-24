"use client";

import type { TrainedModel } from "@wasifyai/client";
import { Loader2 } from "lucide-react";
import { useId, useState } from "react";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import type { ImageFlowApi } from "../hooks/use-image-flow";
import { actions, hint } from "../styles";
import { useTryIt } from "./use-try-it";

const INPUT =
  "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30";

/** A first prompt that puts the magic word in a scene the model has not seen. */
export function starterPrompt(model: Pick<TrainedModel, "kind" | "trigger_word">): string {
  const word = model.trigger_word;
  return model.kind === "style"
    ? `a lighthouse on a cliff at sunrise, ${word}`
    : model.kind === "object"
      ? `${word} on a wooden table by a window`
      : `${word}, standing in a sunny park`;
}

/** "Use it": the same words drawn without and with what was taught, side by side. */
export function TryIt({ model, runs }: { model: TrainedModel; runs: ImageFlowApi }) {
  const id = useId();
  const [prompt, setPrompt] = useState(() => starterPrompt(model));
  const { state, draw } = useTryIt(runs);
  const style = model.card.published?.lora_name;
  if (model.preview || !style) {
    return (
      <p className={hint}>
        {model.preview
          ? "A preview model cannot draw."
          : "This model is not ready to draw with: the image engine does not have it."}
      </p>
    );
  }
  const working = state.phase === "drawing";
  const ok = prompt.trim().length > 0 && prompt.length <= 500;
  return (
    <section className="grid gap-3" aria-label={`Try ${model.name}`}>
      <h3 className="m-0 font-semibold">Try it</h3>
      <div className="grid gap-1.5">
        <label htmlFor={id} className="font-medium text-sm">
          What to draw
        </label>
        <input
          id={id}
          className={INPUT}
          value={prompt}
          maxLength={500}
          disabled={working}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <p className={hint}>
          It is drawn twice with the same settings: once without {model.name}, once with it.
        </p>
      </div>
      <div className={actions}>
        <Button type="button" disabled={!ok || working} onClick={() => void draw(prompt, style)}>
          {working ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
          {working ? "Drawing…" : "Draw it"}
        </Button>
      </div>
      {state.phase === "drawing" ? (
        <output className="text-muted-foreground text-sm">
          {state.step === 1
            ? `Drawing it without ${model.name} (1 of 2)…`
            : `Drawing it with ${model.name} (2 of 2)…`}
        </output>
      ) : null}
      {state.phase === "failed" ? (
        <Notice tone="error" title="It could not be drawn">
          {state.message}
        </Notice>
      ) : null}
      {state.phase === "done" ? (
        <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
          {(
            [
              [`Without ${model.name}`, state.without],
              [`With ${model.name}`, state.with],
            ] as const
          ).map(([label, image]) => (
            <li key={label} className="grid gap-1.5">
              <img
                src={image.imageUrl}
                alt={label}
                className="aspect-square w-full rounded-lg border object-cover"
              />
              <span className="font-medium text-sm">{label}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
