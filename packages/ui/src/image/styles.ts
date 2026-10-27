"use client";

import type { TrainedModel, TrainingApi } from "@wasifyai/client";
import { useEffect, useState } from "react";
import type { LoraOption } from "./ImageWorkspace";

/** The styles among a person's trained models: the picture ones that are published to the image engine. */
export function styleOptionsOf(models: TrainedModel[]): LoraOption[] {
  return models.flatMap((m) => {
    const name = m.card.published?.lora_name;
    return m.card.family !== "video" && m.kind !== "writing" && m.kind !== "decision" && name
      ? [{ name, title: m.name }]
      : [];
  });
}

/** Read the styles once when the screen opens; none (or no way to read them) is fine: the chooser stays as it was. */
export function useImageStyles(api: Pick<TrainingApi, "models">): LoraOption[] {
  const [styles, setStyles] = useState<LoraOption[]>([]);
  useEffect(() => {
    let alive = true;
    api
      .models()
      .then((models) => {
        if (alive) setStyles(styleOptionsOf(models));
      })
      .catch(() => {
        if (alive) setStyles([]);
      });
    return () => {
      alive = false;
    };
  }, [api]);
  return styles;
}
