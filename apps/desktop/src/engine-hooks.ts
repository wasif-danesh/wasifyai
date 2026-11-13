// SPDX-License-Identifier: AGPL-3.0-only
// What the image and video screens both need to know: which model they run and whether the image engine
// (ComfyUI) is set up.
import { useChoicesFor, useChoicesVersion } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { modelsApi } from "./api";
import { componentStatus, onComponentStatus } from "./components";
import { COMFYUI, type ComponentStatus } from "./engine";
import type { ModelEntry } from "./models";

/** The first model of a product in the catalogue, or null while it is read. */
export function useModelOf(productId: string, chosen?: string | null): ModelEntry | null {
  const [model, setModel] = useState<ModelEntry | null>(null);
  useEffect(() => {
    let gone = false;
    modelsApi
      .overview()
      .then((o) => {
        if (gone) return;
        const of = o.models.filter((m) => m.product_id === productId);
        // the person's choice (ADR-0097), else the product's first model
        setModel(of.find((m) => m.id === chosen) ?? of[0] ?? null);
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [productId, chosen]);
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

/** The Images and Video menu items: the product, the picker group and the capability each needs (ADR-0097). */
export const MODEL_ITEMS: Record<
  string,
  { product: string; group: "images" | "video"; verb: string }
> = {
  "images.create": { product: "wasifyai-image", group: "images", verb: "image.generate" },
  "images.edit": { product: "wasifyai-image", group: "images", verb: "image.edit" },
  "images.reference": { product: "wasifyai-image", group: "images", verb: "image.reference" },
  "images.inpaint": { product: "wasifyai-image", group: "images", verb: "image.inpaint" },
  "video.create": { product: "wasifyai-video", group: "video", verb: "video.generate" },
  "video.animate": { product: "wasifyai-video", group: "video", verb: "video.animate" },
  "video.extend": { product: "wasifyai-video", group: "video", verb: "video.extend" },
};

/**
 * The menu items the chosen image or video model cannot do (ADR-0097): they are not shown. Empty while nothing
 * is read, and for a group on the person's key or a product of one model.
 */
export function useItemsTheModelCannotDo(): ReadonlySet<string> {
  const images = useChoicesFor("images");
  const video = useChoicesFor("video");
  const version = useChoicesVersion();
  const [cannot, setCannot] = useState<ReadonlySet<string>>(new Set());
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    let gone = false;
    Promise.all([images?.list(), video?.list(), modelsApi.overview()])
      .then(([imageRows, videoRows, o]) => {
        if (gone) return;
        const chosen = {
          images: imageRows?.choices.find((c) => c.chosen)?.id,
          video: videoRows?.choices.find((c) => c.chosen)?.id,
        };
        const hidden = Object.entries(MODEL_ITEMS).filter(([, item]) => {
          const can = o.models.find(
            (m) => m.product_id === item.product && m.id === chosen[item.group],
          )?.can;
          return can !== undefined && can.length > 0 && !can.includes(item.verb);
        });
        setCannot(new Set(hidden.map(([id]) => id)));
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [images, video, version]);
  return cannot;
}
