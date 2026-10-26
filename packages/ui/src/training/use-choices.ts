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

  useEffect(() => {
    let alive = true;
    setChoices(null);
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
  }, [api, kind, family]);

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
    pickBase: (id: string) => {
      setBase(id);
      setMethod(null); // a new model starts from its own recommendation
    },
    pickMethod: setMethod,
  };
}

export type Choosing = ReturnType<typeof useChoices>;
