import type { ChatPart, ImageSummary, ImagesApi } from "@wasifyai/client";
import { ImageIcon, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../components/button";
import { Spinner } from "../components/spinner";

type Tool = Extract<ChatPart, { type: "tool" }>;

export type ToolCardProps = {
  tool: Tool;
  images: ImagesApi;
  /** Open a creation in its own screen (the library for an image). */
  onOpenCreation?: (kind: string, id: string) => void;
};

function Picture({
  imageId,
  images,
  onOpen,
}: {
  imageId: string;
  images: ImagesApi;
  onOpen?: () => void;
}) {
  const [image, setImage] = useState<ImageSummary | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let gone = false;
    images
      .get(imageId)
      .then((i) => !gone && setImage(i))
      .catch(() => !gone && setMissing(true));
    return () => {
      gone = true;
    };
  }, [imageId, images]);
  if (missing)
    return <p className="text-muted-foreground text-sm">This picture is no longer there.</p>;
  if (!image) return <div className="aspect-square w-64 animate-pulse rounded-lg bg-muted" />;
  return (
    <figure className="m-0 grid w-fit max-w-sm gap-2">
      <img
        src={image.image_url}
        alt={image.prompt}
        width={image.width || undefined}
        height={image.height || undefined}
        className="h-auto max-h-96 w-auto max-w-full rounded-lg border object-contain"
      />
      <figcaption className="flex flex-wrap items-center gap-2 text-muted-foreground text-xs">
        <span className="min-w-0 max-w-full truncate">{image.prompt}</span>
        {onOpen ? (
          <Button type="button" size="sm" variant="outline" onClick={onOpen}>
            Open in the library
          </Button>
        ) : null}
      </figcaption>
    </figure>
  );
}

/** A tool the assistant used, as part of its answer: a picture being made and then shown, or what a
 * search found. */
export function ToolCard({ tool, images, onOpenCreation }: ToolCardProps) {
  if (tool.name === "generate_image") {
    if (tool.status === "running") {
      const queued = tool.jobStatus === "queued";
      const pct = typeof tool.progress === "number" ? Math.round(tool.progress * 100) : null;
      return (
        <output className="flex items-center gap-3 rounded-lg border p-3 text-sm">
          <Spinner />
          <span>
            {queued
              ? tool.queuePosition && tool.queuePosition > 1
                ? `Waiting for a turn, place ${tool.queuePosition}`
                : "Waiting for a turn"
              : pct !== null && pct > 0
                ? `Making your picture, ${pct}%`
                : "Making your picture"}
          </span>
        </output>
      );
    }
    if (tool.status === "ok" && typeof tool.output?.image_id === "string") {
      const id = tool.output.image_id;
      return (
        <Picture
          imageId={id}
          images={images}
          onOpen={onOpenCreation ? () => onOpenCreation("image", id) : undefined}
        />
      );
    }
    return (
      <p className="flex items-center gap-2 rounded-lg border p-3 text-sm">
        <ImageIcon className="size-4 shrink-0" aria-hidden="true" />
        {tool.status === "refused"
          ? String(tool.output?.message ?? "That picture was not made.")
          : "The picture could not be made."}
      </p>
    );
  }
  if (tool.name === "search_creations") {
    if (tool.status === "running") {
      return (
        <output className="flex items-center gap-3 rounded-lg border p-3 text-sm">
          <Spinner /> Looking through your library
        </output>
      );
    }
    const results = Array.isArray(tool.output?.results)
      ? (tool.output.results as { kind: string; id: string; text?: string }[])
      : [];
    return (
      <div className="grid gap-2 rounded-lg border p-3 text-sm">
        <p className="flex items-center gap-2 font-medium">
          <Search className="size-4" aria-hidden="true" />
          {results.length ? `Found ${results.length} in your library` : "Nothing matched"}
        </p>
        {results.length ? (
          <ul className="grid gap-1">
            {results.map((r) => (
              <li key={`${r.kind}-${r.id}`} className="flex items-center gap-2">
                <span className="truncate">{r.text || r.id}</span>
                <span className="text-muted-foreground text-xs">{r.kind}</span>
                {onOpenCreation ? (
                  <button
                    type="button"
                    className="ms-auto text-xs underline underline-offset-4"
                    onClick={() => onOpenCreation(r.kind, r.id)}
                  >
                    Open
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    );
  }
  return null;
}
