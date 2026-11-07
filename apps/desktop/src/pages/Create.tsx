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
import { useRef } from "react";
import { client, stylesApi } from "../api";
import { useGroupReady } from "../choices/use-ready";
import { useImageEngine, useModelOf } from "../engine-hooks";
import { images } from "../images";
import type { Route } from "../router";

/** the capability each screen asks for, and what it does in words */
const VERB: Record<ImageMode, string> = {
  text: "image.generate",
  image: "image.edit",
  reference: "image.reference",
  inpaint: "image.inpaint",
};
const CANNOT: Record<ImageMode, string> = {
  text: "make a picture from words",
  image: "change a picture",
  reference: "combine two pictures",
  inpaint: "change a painted area",
};

export function CreatePage({
  mode,
  go,
  preset,
  onEditThis,
  onAnimateThis,
  source,
}: {
  mode: ImageMode;
  go: (r: Route) => void;
  preset?: WorkspacePreset | null;
  onEditThis?: (image: ImageSummary) => void;
  onAnimateThis?: (image: ImageSummary) => void;
  source?: { url: string; name: string; id?: string } | null;
}) {
  // "Select image model": the model in use, or the way to get one (ADR-0086)
  const choices = useChoicesFor("images");
  const picker = useRef<ModelSelectHandle>(null);
  const { ensure, keyed, chosen } = useGroupReady(choices, picker);
  const model = useModelOf("wasifyai-image", keyed ? null : chosen);
  const engine = useImageEngine();
  // the chosen model makes the picture (ADR-0097); one that cannot do this screen's work says so
  const offered = !keyed && model !== null && model.id === chosen && (model.can?.length ?? 0) > 0;
  const cannot = offered && !model.can?.includes(VERB[mode]);
  const header = <ModelSelect group="images" api={choices} handleRef={picker} />;

  // only a real model can be too big: the placeholder engine runs anywhere
  const real = engine?.state === "installed" && !keyed;
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
      stylesApi={stylesApi}
      onOpenFolders={() => go("settings")}
      onEditThis={onEditThis}
      onAnimateThis={onAnimateThis}
      sourceImage={source ?? null}
      canSave
      model={offered ? model.id : null}
      blockedReason={
        cannot
          ? `${model?.title} cannot ${CANNOT[mode]}. Choose another image model above.`
          : tooBig && model?.fit
            ? `${model.title} will not fit. ${model.fit.reason}`
            : null
      }
    />
  );
}
