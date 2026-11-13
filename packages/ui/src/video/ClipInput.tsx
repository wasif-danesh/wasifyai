"use client";

import { type VideoSummary, clipLength } from "@wasifyai/client";
import { Film, Upload } from "lucide-react";
import { type ChangeEvent, useRef } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { Spinner } from "../components/spinner";

/** How much is added: the new part is 5 or 8 seconds long and repeats the clip's last 9 frames first. */
export const EXTEND_LENGTHS = [
  { seconds: 5, label: "About 5 seconds", note: "a few minutes" },
  { seconds: 8, label: "About 8 seconds", note: "takes about twice as long" },
] as const;

/**
 * The clip Extend carries on (stage U4 of the UI plan): the chosen clip, or a drop zone that says to choose
 * one from the recent strip under the stage or to add a video file from this computer. The list of clips is
 * the strip; this is only what is chosen and the way in for a file.
 */
export function ClipInput({
  source,
  dragging,
  adding,
  problem,
  canAdd,
  onAdd,
  onClear,
}: {
  source: VideoSummary | null;
  /** a file is being dragged over the page */
  dragging?: boolean;
  /** a file is on its way to the engine */
  adding?: boolean;
  /** why the last file could not be added */
  problem?: string | null;
  /** whether a file from this computer can be added (the engine offers it) */
  canAdd: boolean;
  onAdd: (file: File) => void;
  onClear: () => void;
}) {
  const picker = useRef<HTMLInputElement>(null);

  function picked(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // the same file can be chosen again
    if (file) onAdd(file);
  }

  return (
    <section className="grid gap-2" aria-label="Your video">
      <h2 className="m-0 font-semibold text-ui-lg">Which video should carry on?</h2>
      {canAdd ? (
        <input
          ref={picker}
          type="file"
          accept="video/*,.mp4,.mov,.m4v,.webm,.mkv"
          className="sr-only"
          tabIndex={-1}
          aria-label="Choose a video file"
          onChange={picked}
        />
      ) : null}
      {source ? (
        <div className="flex items-center gap-3 rounded-md border p-2">
          {source.poster_url ? (
            <img
              src={source.poster_url}
              alt=""
              className="aspect-video w-28 shrink-0 rounded bg-muted object-cover"
            />
          ) : (
            <span className="grid aspect-video w-28 shrink-0 place-items-center rounded bg-muted">
              <Film className="size-5 text-muted-foreground" aria-hidden="true" />
            </span>
          )}
          <div className="grid min-w-0 flex-1 gap-1">
            <span className="line-clamp-2 text-sm">
              {source.mode === "import" ? "A video you added" : source.prompt}
            </span>
            <span className="text-muted-foreground text-xs">{clipLength(source.seconds)}</span>
          </div>
          <Button type="button" size="sm" variant="ghost" onClick={onClear}>
            Remove
          </Button>
        </div>
      ) : (
        <div
          data-dragging={dragging || undefined}
          className={cn(
            "grid justify-items-center gap-2 rounded-md border border-dashed px-4 py-5 text-center text-muted-foreground text-sm",
            "data-[dragging]:border-primary data-[dragging]:bg-accent",
          )}
        >
          <Film className="size-5" aria-hidden="true" />
          <p className="m-0">
            Choose one of your videos under the result
            {canAdd ? ", or drop a video file here." : "."}
          </p>
          {canAdd ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={adding}
              onClick={() => picker.current?.click()}
            >
              {adding ? <Spinner /> : <Upload className="size-4" />} Add a video from this computer
            </Button>
          ) : null}
        </div>
      )}
      <p className="m-0 text-muted-foreground text-xs" aria-live="polite">
        {adding
          ? "Adding your video… this takes a moment."
          : canAdd
            ? "A file can be up to 30 seconds. It is made to fit the model; the original is not changed."
            : null}
      </p>
      {problem ? (
        <Notice tone="error" title="That video could not be added">
          {problem}
        </Notice>
      ) : null}
    </section>
  );
}
