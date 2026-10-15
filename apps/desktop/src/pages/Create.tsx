// SPDX-License-Identifier: AGPL-3.0-only
// Create and Edit: the shared two-panel screen with this window's model chip and setup notices.
import { ImageStudio, Notice, type StudioPreset, cn } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { client, modelsApi } from "../api";
import { COMFYUI, type ComponentStatus, componentStatus, onComponentStatus } from "../engine";
import { images } from "../images";
import type { ModelEntry } from "../models";
import type { Route } from "../router";

function useModel(): ModelEntry | null {
  const [model, setModel] = useState<ModelEntry | null>(null);
  useEffect(() => {
    let gone = false;
    modelsApi
      .overview()
      .then((o) => !gone && setModel(o.models[0] ?? null))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, []);
  return model;
}

function useImageEngine(): ComponentStatus | null {
  const [status, setStatus] = useState<ComponentStatus | null>(null);
  useEffect(() => {
    let stop: (() => void) | undefined;
    let gone = false;
    componentStatus(COMFYUI)
      .then((s) => !gone && setStatus(s))
      .catch(() => {});
    onComponentStatus((id, s) => id === COMFYUI && !gone && setStatus(s)).then((off) => {
      stop = off;
      if (gone) off();
    });
    return () => {
      gone = true;
      stop?.();
    };
  }, []);
  return status;
}

export function CreatePage({
  mode,
  go,
  preset,
}: {
  mode: "text" | "image";
  go: (r: Route) => void;
  preset?: StudioPreset | null;
}) {
  const model = useModel();
  const engine = useImageEngine();

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
    </>
  );

  const notices = (
    <>
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
    <ImageStudio
      mode={mode}
      runs={client}
      images={images}
      header={header}
      notices={notices}
      preset={preset}
      onOpenLibrary={() => go("library")}
      canSave
    />
  );
}
