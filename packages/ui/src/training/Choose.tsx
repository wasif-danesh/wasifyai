"use client";

import type { TrainMethod } from "@wasifyai/client";
import { useId } from "react";
import { cn } from "../cn";
import { hint } from "../styles";
import type { Choosing } from "./use-choices";

const ROW =
  "flex items-start gap-3 rounded-lg border px-3 py-2 has-[:checked]:border-primary has-[:disabled]:opacity-60";

function MethodRow({ m, group, c }: { m: TrainMethod; group: string; c: Choosing }) {
  return (
    <label className={ROW}>
      <input
        type="radio"
        name={group}
        className="mt-1"
        checked={c.method === m.id}
        disabled={!m.can}
        onChange={() => c.pickMethod(m.id)}
      />
      <span className="grid gap-0.5">
        <span>
          {m.title} <span className="text-muted-foreground">({m.technical})</span>
        </span>
        {m.can ? null : <span className={hint}>{m.reason}</span>}
      </span>
    </label>
  );
}

/**
 * "How to teach it" (ADR-0073, amendment 2026-10-24): the method, closed by default, so the main path stays three
 * steps and one recommendation. The model is chosen above it with "Model to teach" (amendment 2026-11-07). Words
 * first, the technical name second; what cannot be used is listed with the reason, never hidden.
 */
export function Choose({ c }: { c: Choosing }) {
  const methodGroup = useId();
  if (!c.choices || c.choices.bases.length === 0) return null;
  const rec = c.choices.bases.find((b) => b.id === c.choices?.default_base);
  const simple = c.row?.methods.filter((m) => !m.advanced) ?? [];
  const expert = c.row?.methods.filter((m) => m.advanced) ?? [];
  return (
    <details className="rounded-lg border px-3 py-2">
      <summary className="cursor-pointer font-semibold">
        How to teach it
        <span className="ml-2 font-normal text-muted-foreground">
          {c.choice.method
            ? (c.row?.methods.find((m) => m.id === c.method)?.title ?? "")
            : "Recommended"}
        </span>
      </summary>
      <div className="mt-3 grid gap-4">
        {c.row ? (
          <fieldset className="m-0 grid gap-2 border-0 p-0">
            <legend className="mb-1 font-semibold">Method</legend>
            {simple.map((m) => (
              <MethodRow key={m.id} m={m} group={methodGroup} c={c} />
            ))}
            {expert.length > 0 ? (
              <details className={cn("rounded-lg border px-3 py-2")}>
                <summary className="cursor-pointer">For experts</summary>
                <div className="mt-2 grid gap-2">
                  {expert.map((m) => (
                    <MethodRow key={m.id} m={m} group={methodGroup} c={c} />
                  ))}
                </div>
              </details>
            ) : null}
          </fieldset>
        ) : null}
        <p className={hint}>
          Leave this closed and the app teaches {c.row?.title ?? rec?.title ?? "the model"} the way
          it recommends.
        </p>
      </div>
    </details>
  );
}
