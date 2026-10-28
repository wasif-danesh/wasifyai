// SPDX-License-Identifier: AGPL-3.0-only
// What the image and video screens both need to know: which model they run and whether the image engine
// (ComfyUI) is set up.
import { useEffect, useState } from "react";
import { modelsApi } from "./api";
import { componentStatus, onComponentStatus } from "./components";
import { COMFYUI, type ComponentStatus } from "./engine";
import type { ModelEntry } from "./models";

/** The first model of a product in the catalogue, or null while it is read. */
export function useModelOf(productId: string): ModelEntry | null {
  const [model, setModel] = useState<ModelEntry | null>(null);
  useEffect(() => {
    let gone = false;
    modelsApi
      .overview()
      .then((o) => !gone && setModel(o.models.find((m) => m.product_id === productId) ?? null))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [productId]);
  return model;
}

/** The state of the image engine, kept up to date while the screen is open. */
export function useImageEngine(): ComponentStatus | null {
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
