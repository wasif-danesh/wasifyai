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
 * "Choose the model and method" (ADR-0073, amendment 2026-10-24): closed by default, so the main path stays three
 * steps and one recommendation. Words first, the technical name second; what cannot be used is listed with the
 * reason, never hidden.
 */
export function Choose({ c }: { c: Choosing }) {
  const baseGroup = useId();
  const methodGroup = useId();
  if (!c.choices || c.choices.bases.length === 0) return null;
  const rec = c.choices.bases.find((b) => b.id === c.choices?.default_base);
  const simple = c.row?.methods.filter((m) => !m.advanced) ?? [];
  const expert = c.row?.methods.filter((m) => m.advanced) ?? [];
  return (
    <details className="rounded-lg border px-3 py-2">
      <summary className="cursor-pointer font-semibold">
        Choose the model and method
        <span className="ml-2 font-normal text-muted-foreground">
          {c.changed
            ? `${c.row?.title ?? ""}, ${c.row?.methods.find((m) => m.id === c.method)?.title.toLowerCase() ?? ""}`
            : "Recommended"}
        </span>
      </summary>
      <div className="mt-3 grid gap-4">
        <fieldset className="m-0 grid gap-2 border-0 p-0">
          <legend className="mb-1 font-semibold">Model to teach</legend>
          {c.choices.bases.map((b) => (
            <label key={b.id || b.title} className={ROW}>
              <input
                type="radio"
                name={baseGroup}
                className="mt-1"
                checked={b.id !== "" && c.base === b.id}
                disabled={!b.can_teach}
                onChange={() => c.pickBase(b.id)}
              />
              <span className="grid gap-0.5">
                <span>
                  {b.title}
                  {b.recommended ? (
                    <span className="ml-2 rounded-full border px-2 py-0.5 text-xs">
                      Recommended
                    </span>
                  ) : null}
                </span>
                <span className={hint}>
                  {b.can_teach
                    ? [b.licence, "on this computer"].filter(Boolean).join(", ")
                    : b.reason}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        {c.row ? (
          <fieldset className="m-0 grid gap-2 border-0 p-0">
            <legend className="mb-1 font-semibold">How to teach it</legend>
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
          Leave this closed and the app teaches {rec?.title ?? "the recommended model"} as a small
          adapter.
        </p>
      </div>
    </details>
  );
}
