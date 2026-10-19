"use client";

import { useId, useRef } from "react";
import { cn } from "../cn";
import type { Picture } from "../hooks/use-picture";
import { ACCEPTED_TYPES } from "../pictures";
import { actions, field, fieldError, fieldLabel, hint } from "../styles";
import { Button } from "./button";
import { Label } from "./label";
import { Bar } from "./progress-bar";

/**
 * The picture field shared by the products that take one (ADR-0039): a button to choose, a place to drop,
 * paste handled by the form (see `usePictureEvents`), a preview and Replace / Remove. Presentational: the
 * state and the upload live in `usePicture`.
 */
export function PictureInput({
  picture,
  status,
  error,
  dragging = false,
  onChoose,
  onRemove,
  onCancel,
}: {
  picture: Picture | null;
  status: "idle" | "uploading" | "error";
  error: string | null;
  dragging?: boolean;
  onChoose: (file: File) => void;
  onRemove: () => void;
  onCancel: () => void;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const uploading = status === "uploading";

  return (
    <div className={field}>
      <Label asChild className={fieldLabel}>
        <span>Your picture</span>
      </Label>
      <input
        ref={input}
        id={`${id}-file`}
        className="sr-only"
        type="file"
        accept={ACCEPTED_TYPES.join(",")}
        aria-label="Your picture"
        aria-describedby={`${id}-hint`}
        tabIndex={-1}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = ""; // choosing the same file again must still fire
          if (file) onChoose(file);
        }}
      />

      {picture ? (
        <div
          className="grid justify-items-start gap-[0.6rem]"
          data-uploading={uploading || undefined}
        >
          <img
            className={cn(
              "max-h-64 max-w-[min(100%,22rem)] rounded-lg border object-contain",
              uploading && "opacity-60",
            )}
            src={picture.previewUrl}
            alt="Preview of your upload"
          />
          <div className={actions}>
            <Button
              type="button"
              variant="outline"
              onClick={() => input.current?.click()}
              disabled={uploading}
            >
              Replace
            </Button>
            <Button type="button" variant="outline" onClick={onRemove}>
              Remove
            </Button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="grid cursor-pointer justify-items-center gap-1 rounded-lg border-2 border-dashed bg-surface px-4 py-[1.6rem] text-center text-foreground transition-colors enabled:hover:border-primary enabled:hover:bg-accent disabled:cursor-progress disabled:opacity-60 data-[dragging]:border-primary data-[dragging]:bg-accent"
          data-dragging={dragging || undefined}
          aria-describedby={`${id}-hint`}
          onClick={() => input.current?.click()}
          disabled={uploading}
        >
          <span className="font-semibold">Choose a picture</span>
          <span className={hint}>or drag one here, or paste it</span>
        </button>
      )}

      {uploading ? (
        <output className="grid gap-[0.6rem]">
          <div className="flex justify-between gap-4 text-ui-lg text-muted-foreground">
            <span>Uploading your picture…</span>
            <Button type="button" variant="link" size="xs" onClick={onCancel}>
              Cancel
            </Button>
          </div>
          <Bar />
        </output>
      ) : null}

      <span className={hint} id={`${id}-hint`}>
        PNG, JPEG or WebP, up to 10 MB. Your picture is deleted once it has been used.
      </span>
      {error ? (
        <span className={fieldError} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}
