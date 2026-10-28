"use client";

import { ANIMATE } from "@/components/video/VideoScreens";
import { putHandoff, takeHandoff } from "@/lib/handoff";
import { imageDownload, webImages, webTraining } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import type { ImageMode } from "@wasifyai/client";
import {
  ImageLibrary,
  ImageWorkspace,
  ModelSelect,
  type WorkspacePreset,
  presetOf,
  useChoicesFor,
  useImageStyles,
} from "@wasifyai/ui";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export const AGAIN = "image-again";
export const EDIT = "image-edit";

type Start = {
  preset: WorkspacePreset | null;
  source: { url: string; name: string; id?: string } | null;
};

/** Create, Edit, Inpaint and Reference: the shared two-panel screen (also the desktop's), talking to the BFF. A recipe sent from
 * the library ("Make it again") or a result sent to Edit arrives through the tab's session storage. */
export function ImageScreen({ mode }: { mode: ImageMode }) {
  const router = useRouter();
  const choices = useChoicesFor("images");
  const styles = useImageStyles(webTraining); // what the person taught the picture model, if anything
  const [start, setStart] = useState<Start | null>(null);
  useEffect(() => {
    setStart({
      preset: mode === "text" ? takeHandoff<WorkspacePreset>(AGAIN) : null,
      source:
        mode === "image" ? takeHandoff<{ url: string; name: string; id?: string }>(EDIT) : null,
    });
  }, [mode]);

  return (
    <div data-workspace className="h-[calc(100dvh-3rem)] min-h-[32rem]">
      {start ? (
        <ImageWorkspace
          key={`${mode}-${start.preset?.seed ?? ""}-${start.source?.url ?? ""}`}
          mode={mode}
          runs={webClient}
          images={webImages}
          preset={start.preset}
          sourceImage={start.source}
          loras={styles}
          header={
            choices ? (
              <ModelSelect group="images" api={choices} />
            ) : (
              <span className="font-medium">Images</span>
            )
          }
          downloadHref={imageDownload}
          onOpenLibrary={() => router.push("/creations?show=images")}
          onEditThis={(image) => {
            putHandoff(EDIT, { url: image.image_url, name: `${image.id}.png`, id: image.id });
            router.push("/image/edit");
          }}
          onAnimateThis={(image) => {
            putHandoff(ANIMATE, { url: image.image_url, name: `${image.id}.png`, id: image.id });
            router.push("/video/animate");
          }}
        />
      ) : null}
    </div>
  );
}
