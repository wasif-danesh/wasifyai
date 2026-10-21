"use client";

import { putHandoff, takeHandoff } from "@/lib/handoff";
import { imageDownload, webImages } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import type { ImageMode } from "@wasifyai/client";
import { ImageLibrary, ImageWorkspace, type WorkspacePreset, presetOf } from "@wasifyai/ui";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const AGAIN = "image-again";
const EDIT = "image-edit";

type Start = { preset: WorkspacePreset | null; source: { url: string; name: string } | null };

/** Create, Edit, Inpaint and Reference: the shared two-panel screen (also the desktop's), talking to the BFF. A recipe sent from
 * the library ("Make it again") or a result sent to Edit arrives through the tab's session storage. */
export function ImageScreen({ mode }: { mode: ImageMode }) {
  const router = useRouter();
  const [start, setStart] = useState<Start | null>(null);
  useEffect(() => {
    setStart({
      preset: mode === "text" ? takeHandoff<WorkspacePreset>(AGAIN) : null,
      source: mode === "image" ? takeHandoff<{ url: string; name: string }>(EDIT) : null,
    });
  }, [mode]);

  return (
    <div data-workspace className="h-[calc(100dvh-3.5rem)] min-h-[32rem]">
      {start ? (
        <ImageWorkspace
          key={`${mode}-${start.preset?.seed ?? ""}-${start.source?.url ?? ""}`}
          mode={mode}
          runs={webClient}
          images={webImages}
          preset={start.preset}
          sourceImage={start.source}
          header={<span className="font-medium">Images</span>}
          downloadHref={imageDownload}
          onOpenLibrary={() => router.push("/image/library")}
          onEditThis={(image) => {
            putHandoff(EDIT, { url: image.image_url, name: `${image.id}.png` });
            router.push("/image/edit");
          }}
        />
      ) : null}
    </div>
  );
}

/** Your images: everything made, with search, favourites, download, delete and "Make it again". */
export function ImageLibraryScreen() {
  const router = useRouter();
  return (
    <ImageLibrary
      images={webImages}
      className="max-w-none px-0 pt-0 pb-0"
      subtitle="Everything you made."
      downloadHref={imageDownload}
      onCreate={() => router.push("/image")}
      onRunAgain={(image) => {
        const preset = presetOf(image);
        if (!preset) return;
        putHandoff(AGAIN, preset);
        router.push("/image");
      }}
    />
  );
}
