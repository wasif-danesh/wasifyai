// SPDX-License-Identifier: AGPL-3.0-only
// The model picker's source for this window (ADR-0086): for each group, the rows and the work, composed from the
// engine routes the Models page already used. Nothing here is a new engine route.
import type { ChoicesApi, ChoicesSource, GroupId } from "@wasifyai/ui";
import { discoveryApi, hubApi, languageApi, modelsApi, voiceApi } from "../api";
import { model3d } from "../model3d";
import { remembered } from "../remember";
import { CATALOGUE_GROUPS, catalogueChoices } from "./catalogue-choices";
import { chatChoices } from "./chat-choices";
import { createEngines } from "./engines";
import { model3dChoices } from "./model3d-choices";
import { voiceChoices } from "./voice-choices";

/** One source for the window: an adapter is made once per group and task, so screens share its work. */
export function createChoicesSource(engines = createEngines()): ChoicesSource {
  const cache = new Map<string, ChoicesApi | null>();
  const make = (group: GroupId, task?: string): ChoicesApi | null => {
    switch (group) {
      case "chat":
        return chatChoices({
          language: languageApi,
          hub: hubApi,
          discovery: discoveryApi,
          models: modelsApi,
          engines,
        });
      case "images":
      case "video":
      case "documents":
        return catalogueChoices(
          { models: modelsApi, engines, memory: remembered },
          CATALOGUE_GROUPS[group],
        );
      case "three_d":
        return model3dChoices(model3d);
      default:
        return voiceChoices(
          { voice: voiceApi, models: modelsApi, memory: remembered, engines },
          group,
          task,
        );
    }
  };
  return (group, task) => {
    const key = `${group}/${task ?? ""}`;
    if (!cache.has(key)) cache.set(key, make(group, task));
    return cache.get(key) ?? null;
  };
}

export const choicesSource = createChoicesSource();
