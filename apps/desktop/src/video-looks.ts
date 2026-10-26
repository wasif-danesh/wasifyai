// SPDX-License-Identifier: AGPL-3.0-only
// The looks the person taught the video model (Train models): the models they made with `family: "video"` that
// are published to the video engine. Read when the screen opens; none is fine (the chooser stays hidden).
import type { TrainedModel } from "@wasifyai/client";
import type { VideoLook } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { training } from "./training";

export function looksOf(models: TrainedModel[]): VideoLook[] {
  return models.flatMap((m) => {
    const name = m.card.published?.lora_name;
    return m.card.family === "video" && name ? [{ name, title: m.name, word: m.trigger_word }] : [];
  });
}

export function useVideoLooks(): VideoLook[] {
  const [looks, setLooks] = useState<VideoLook[]>([]);
  useEffect(() => {
    let alive = true;
    training
      .models()
      .then((models) => {
        if (alive) setLooks(looksOf(models));
      })
      .catch(() => {
        if (alive) setLooks([]);
      });
    return () => {
      alive = false;
    };
  }, []);
  return looks;
}
