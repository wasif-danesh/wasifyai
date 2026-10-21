// SPDX-License-Identifier: AGPL-3.0-only
// Create, Edit, Reference and Inpaint: the shared two-panel screen with this window's model chip and setup notices.
import type { ImageMode, ImageSummary } from "@wasifyai/client";
import {
  ImageWorkspace,
  ModelSelect,
  type ModelSelectHandle,
  Notice,
  type WorkspacePreset,
  useChoicesFor,
} from "@wasifyai/ui";
import { useEffect, useRef, useState } from "react";
import { client, discoveryApi, lorasApi } from "../api";
import { useGroupReady } from "../choices/use-ready";
import { useImageEngine, useModelOf } from "../engine-hooks";
import { images } from "../images";
import type { LoraList } from "../loras";
import type { Route } from "../router";

function useLoras(): [LoraList, () => void] {
  const [list, setList] = useState<LoraList>({ ready: [], available: [] });
  const [version, setVersion] = useState(0);
  // biome-ignore lint/correctness/useExhaustiveDependencies: `version` is the refresh trigger
  useEffect(() => {
    let gone = false;
    lorasApi
      .list()
      .then((l) => !gone && setList(l))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [version]);
  return [list, () => setVersion((v) => v + 1)];
}

export function CreatePage({
  mode,
  go,
  preset,
  onEditThis,
  source,
}: {
  mode: ImageMode;
  go: (r: Route) => void;
  preset?: WorkspacePreset | null;
  onEditThis?: (image: ImageSummary) => void;
  source?: { url: string; name: string } | null;
}) {
  const model = useModelOf("wasifyai-image");
  const engine = useImageEngine();
  const [loras, refreshLoras] = useLoras();

  // "Select image model": the model in use, or the way to get one (ADR-0086)
  const choices = useChoicesFor("images");
  const picker = useRef<ModelSelectHandle>(null);
  const { ensure } = useGroupReady(choices, picker);
  const header = <ModelSelect group="images" api={choices} handleRef={picker} />;

  // only a real model can be too big: the placeholder engine runs anywhere
  const real = engine?.state === "installed";
  const tooBig = real && model?.fit?.verdict === "too_big";
  const tight = real && model?.fit?.verdict === "tight";

  const notices =
    tight && model?.fit ? (
      <Notice tone="warn" title="This computer is tight on memory">
        {model.fit.reason}
      </Notice>
    ) : null;

  return (
    <ImageWorkspace
      mode={mode}
      runs={client}
      images={images}
      header={header}
      notices={notices}
      beforeMake={ensure}
      preset={preset}
      onOpenLibrary={() => go("library")}
      loras={loras.ready.map((l) => ({ id: l.id, name: l.name, title: l.title, size: l.size }))}
      availableLoras={loras.available.map((l) => ({
        id: l.id,
        name: l.name,
        title: `${l.title} (${l.tool})`,
        size: l.size,
      }))}
      onUseLora={async (id) => {
        await discoveryApi.use(id); // adds the folder; the list reads again once the scan is done
        setTimeout(refreshLoras, 1500);
      }}
      onEditThis={onEditThis}
      sourceImage={source ?? null}
      canSave
      blockedReason={
        tooBig && model?.fit ? `${model.title} will not fit. ${model.fit.reason}` : null
      }
    />
  );
}
