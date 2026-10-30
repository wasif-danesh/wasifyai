// SPDX-License-Identifier: AGPL-3.0-only
// Train (ADR-0073, ADR-0076): the shared screen on this window's engine.
import type { TrainedModel } from "@wasifyai/client";
import { Train, type WorkspacePreset, starterPrompt } from "@wasifyai/ui";
import { client, stylesApi } from "../api";
import type { Route } from "../router";
import { training } from "../training";

/** Create's starting point for a taught picture model: its style chosen, its word in the prompt (ADR-0091). */
export async function presetForModel(model: TrainedModel): Promise<WorkspacePreset> {
  const list = await stylesApi.list().catch(() => null);
  // Train's record names its run; a style adopted from its file name has the first 8 characters of it
  const style = list?.styles.find(
    (s) => s.source.kind === "trained" && s.source.run && model.run_id.startsWith(s.source.run),
  );
  return {
    prompt: starterPrompt(model),
    size: "square",
    seed: null,
    loras: [],
    styles: style ? [{ id: style.id, strength: 1 }] : [],
  };
}

export function TrainPage({
  go,
  onUseInCreate,
}: {
  go: (r: Route) => void;
  onUseInCreate?: (preset: WorkspacePreset) => void;
}) {
  return (
    <Train
      api={training}
      runs={client}
      onOpenLibrary={() => go("library")}
      onUseInCreate={
        onUseInCreate ? (model) => void presetForModel(model).then(onUseInCreate) : undefined
      }
    />
  );
}
