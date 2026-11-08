"use client";

import type {
  TrainChoice,
  TrainChoices,
  TrainFamily,
  TrainKind,
  TrainMethodId,
  TrainingApi,
} from "@wasifyai/client";
import { useEffect, useMemo, useState } from "react";

/**
 * The models and methods that can be chosen for a kind of teaching (ADR-0073, amendment 2026-10-24). Nothing chosen
 * means the recommendation: `choice` holds only what the person changed, and the engine fills in the rest.
 */
export function useChoices(api: TrainingApi, kind: TrainKind, family: TrainFamily = "image") {
  const [choices, setChoices] = useState<TrainChoices | null>(null);
  const [base, setBase] = useState<string | null>(null);
  const [method, setMethod] = useState<TrainMethodId | null>(null);
  const [round, setRound] = useState(0); // read the list again (after a model's files arrive)

  useEffect(() => {
    let alive = true;
    if (round === 0) setChoices(null); // a reload keeps the list shown while it is read
    api
      .choices(kind, family)
      .then((c) => {
        if (alive) setChoices(c);
      })
      .catch(() => {
        if (alive) setChoices(null); // the recommendation still works without the list
      });
    return () => {
      alive = false;
    };
  }, [api, kind, family, round]);

  const chosenBase = base ?? choices?.default_base ?? "";
  const row = choices?.bases.find((b) => b.id === chosenBase) ?? null;
  const chosenMethod = method ?? choices?.default_method ?? "lora";

  /** A method the chosen model cannot use falls back to the recommendation. */
  const usable = row?.methods.find((m) => m.id === chosenMethod)?.can !== false;

  const choice: TrainChoice = useMemo(() => {
    const out: TrainChoice = {};
    if (base && base !== choices?.default_base) out.base = base;
    if (method && usable && method !== choices?.default_method) out.method = method;
    return out;
  }, [base, method, usable, choices]);

  return {
    choices,
    row,
    base: chosenBase,
    method: usable ? chosenMethod : (choices?.default_method ?? "lora"),
    choice,
    changed: Object.keys(choice).length > 0,
    reload: () => setRound((n) => n + 1),
    pickBase: (id: string) => {
      setBase(id);
      setMethod(null); // a new model starts from its own recommendation
    },
    pickMethod: setMethod,
  };
}

export type Choosing = ReturnType<typeof useChoices>;
