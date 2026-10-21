// SPDX-License-Identifier: AGPL-3.0-only
// Create, Edit, Reference and Inpaint: the shared two-panel screen with this window's model chip and setup notices.
import type { ImageMode, ImageSummary } from "@wasifyai/client";
import { ImageWorkspace, Notice, type WorkspacePreset, cn } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { FitBadge } from "../FitBadge";
import { client, discoveryApi, lorasApi } from "../api";
import { useImageEngine, useModelOf } from "../engine-hooks";
import { images } from "../images";
import type { LoraList } from "../loras";
import type { ModelEntry } from "../models";
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

  const header = (
    <>
      <span className="font-medium">{model?.title ?? "Image model"}</span>
      {model ? (
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-xs",
            model.status === "ready" ? "text-ok" : "text-muted-foreground",
          )}
        >
          {model.status === "ready" ? "ready" : "not downloaded"}
        </span>
      ) : null}
      {model?.fit ? <FitBadge fit={model.fit} /> : null}
    </>
  );

  // only a real model can be too big: the placeholder engine runs anywhere
  const real = engine?.state === "installed";
  const tooBig = real && model?.fit?.verdict === "too_big";
  const tight = real && model?.fit?.verdict === "tight";

  const notices = (
    <>
      {tight && model?.fit ? (
        <Notice tone="warn" title="This computer is tight on memory">
          {model.fit.reason}
        </Notice>
      ) : null}
      {engine?.state === "not_installed" ? (
        <Notice tone="info" title="Placeholder pictures">
          Real images need the image engine set up once.{" "}
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => go("settings")}
          >
            Open Settings
          </button>
          .
        </Notice>
      ) : null}
      {model && model.status !== "ready" && engine?.state === "installed" ? (
        <Notice tone="warn" title="The model is not on this computer yet">
          Get it in{" "}
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => go("models")}
          >
            Models
          </button>{" "}
          before making real images.
        </Notice>
      ) : null}
    </>
  );

  return (
    <ImageWorkspace
      mode={mode}
      runs={client}
      images={images}
      header={header}
      notices={notices}
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
