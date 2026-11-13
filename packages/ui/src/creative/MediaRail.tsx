"use client";
// The right of the screen: everything made for this project, newest first. It is the library filtered by the
// project, with the song always there.
import type { Shot } from "@wasifyai/client";
import { X } from "lucide-react";
import { Button } from "../components/button";
import { type Entry, coverOf, indexKindOf, toRow } from "../creations/model";

export function MediaRail({
  entries,
  tags,
  songId,
  shots,
  onRemove,
}: {
  entries: Entry[];
  tags: { kind: string; item_id: string; shot_id: string | null }[];
  songId?: string;
  shots: Shot[];
  onRemove: (kind: string, id: string) => void;
}) {
  const shotOf = (entry: Entry) => {
    const kind = indexKindOf(entry.kind);
    const tag = tags.find((t) => t.kind === kind && t.item_id === entry.id);
    const at = tag?.shot_id ? shots.findIndex((s) => s.id === tag.shot_id) : -1;
    return at < 0 ? null : `Shot ${at + 1}`;
  };
  return (
    <ul className="m-0 flex list-none gap-2 overflow-x-auto p-2 @4xl:grid @4xl:content-start @4xl:overflow-x-visible">
      {entries.map((entry) => {
        const row = toRow(entry);
        const cover = coverOf(entry);
        const kind = indexKindOf(entry.kind);
        const isSong = entry.kind === "song" && entry.id === songId;
        const shot = shotOf(entry);
        return (
          <li key={row.key} className="relative grid w-28 shrink-0 gap-1 @4xl:w-full">
            {cover ? (
              <img src={cover} alt="" className="aspect-video w-full rounded-md object-cover" />
            ) : (
              <span className="grid aspect-video w-full place-items-center rounded-md bg-muted px-1 text-center text-muted-foreground text-xs">
                {isSong ? "Song" : row.kindLabel}
              </span>
            )}
            <span className="truncate text-xs" title={row.title}>
              {row.title}
            </span>
            {shot ? <span className="text-muted-foreground text-xs">{shot}</span> : null}
            {isSong ? null : (
              <Button
                type="button"
                variant="secondary"
                size="icon"
                className="absolute end-1 top-1 size-6"
                aria-label={`Take out of this project: ${row.title}`}
                onClick={() => onRemove(kind, entry.id)}
              >
                <X aria-hidden className="size-3.5" />
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
