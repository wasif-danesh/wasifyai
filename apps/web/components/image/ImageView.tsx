"use client";

import { DeleteControls } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { actions, eyebrow, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { ImageSummary } from "@wasifyai/contracts";

/** A saved image: the picture, its prompt, a download and a two-step delete. */
export function ImageView({ image, when }: { image: ImageSummary; when: string }) {
  return (
    <article className={cn(panel, "@container")}>
      <figure className="m-0 grid justify-items-center">
        <img
          className="h-auto max-w-full rounded-xl shadow-card"
          src={image.image_url}
          alt={image.prompt}
          width={image.width}
          height={image.height}
        />
      </figure>
      <div className="grid gap-[0.9rem]">
        <span className={eyebrow}>
          {image.mode === "image" ? "Edited picture" : "From text"} · {when}
        </span>
        <p>{image.prompt}</p>
        <div className={actions}>
          <Button asChild>
            <a href={`/api/products/wasifyai-image/images/${image.id}/download`} download>
              Download
            </a>
          </Button>
          <DeleteControls url={`/api/products/wasifyai-image/images/${image.id}`} noun="image" />
        </div>
      </div>
    </article>
  );
}
