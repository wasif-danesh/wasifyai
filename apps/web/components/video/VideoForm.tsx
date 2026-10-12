"use client";

import { EnhanceButton } from "@/components/EnhanceButton";
import { PictureInput } from "@/components/PictureInput";
import { ModeTabs, PromptField } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Spinner } from "@/components/ui/spinner";
import { type Picture, usePicture } from "@/hooks/use-picture";
import { usePictureEvents } from "@/hooks/use-picture-events";
import { chips, field, fieldLabel, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { Mode } from "@/lib/video-flow";
import { type FormEvent, useId, useState } from "react";

export const MAX_PROMPT = 500;
const PRODUCT = "wasifyai-video";

export const SHAPES = [
  { id: "landscape", label: "Landscape", hint: "3:2" },
  { id: "portrait", label: "Portrait", hint: "2:3" },
  { id: "square", label: "Square", hint: "1:1" },
] as const;

/** Clips are 2 or 5 seconds; a longer one does not fit the time a GPU job may take (ADR-0037). */
export const LENGTHS = [
  { seconds: 2, label: "2 seconds", wait: "about 3 minutes" },
  { seconds: 5, label: "5 seconds", wait: "about 8 minutes" },
] as const;

const EXAMPLES: Record<Mode, string[]> = {
  text: [
    "A red fox walks through fresh snow at dawn, the camera slowly follows it",
    "Waves roll onto a quiet beach at sunset, seagulls drifting overhead",
    "A paper boat floats down a rain-soaked street, ripples spreading around it",
  ],
  image: [
    "Snow begins to fall softly and the camera slowly pushes in",
    "Clouds drift across the sky and the grass moves in the wind",
    "The light flickers gently and the camera slowly pans right",
  ],
};

/** What the form hands over: the picture is already uploaded (ADR-0039), so a run needs only its key. */
export type VideoFormValue = {
  mode: Mode;
  prompt: string;
  shape: string;
  seconds: number;
  picture: Picture | null;
};

export function VideoForm({
  onSubmit,
  initial,
  busy = false,
}: {
  onSubmit: (value: VideoFormValue) => void;
  initial?: Partial<Pick<VideoFormValue, "mode" | "prompt" | "shape" | "seconds">>;
  busy?: boolean;
}) {
  const id = useId();
  const [mode, setMode] = useState<Mode>(initial?.mode ?? "text");
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [shape, setShape] = useState(initial?.shape ?? "landscape");
  const [seconds, setSeconds] = useState<number>(initial?.seconds ?? 2);
  const pic = usePicture(PRODUCT);
  // A picture dropped or pasted while on "From text" switches to the picture mode.
  const { dragging } = usePictureEvents((file) => {
    setMode("image");
    void pic.choose(file);
  });

  const trimmed = prompt.trim();
  const valid =
    trimmed.length > 0 &&
    prompt.length <= MAX_PROMPT &&
    (mode === "text" || (pic.picture !== null && pic.status !== "uploading"));
  const wait = LENGTHS.find((l) => l.seconds === seconds)?.wait ?? "a few minutes";

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!valid || busy) return;
    if (mode === "image") pic.handOver(); // the run owns the picture from here
    onSubmit({
      mode,
      prompt: trimmed,
      shape,
      seconds,
      picture: mode === "image" ? pic.picture : null,
    });
  }

  return (
    <form
      className={cn(
        panel,
        "gap-6 data-[dragging]:outline-2 data-[dragging]:outline-offset-4 data-[dragging]:outline-primary data-[dragging]:outline-dashed",
      )}
      onSubmit={submit}
      data-dragging={dragging || undefined}
    >
      <ModeTabs mode={mode} onChange={setMode} />

      {mode === "image" ? (
        <PictureInput
          picture={pic.picture}
          status={pic.status}
          error={pic.error}
          dragging={dragging}
          onChoose={(f) => void pic.choose(f)}
          onRemove={pic.clear}
          onCancel={pic.cancel}
        />
      ) : null}

      <PromptField
        id={id}
        label={mode === "text" ? "What should the video show?" : "What should move?"}
        value={prompt}
        onChange={setPrompt}
        placeholder={EXAMPLES[mode][0]}
        hintText={
          mode === "image"
            ? "Describe the picture and what moves in it. Press Ctrl or ⌘ + Enter to start."
            : "Describe the scene and how it moves. Press Ctrl or ⌘ + Enter to start."
        }
        max={MAX_PROMPT}
        examples={EXAMPLES[mode]}
        exampleLabel={(ex) => ex.split(",")[0]}
        enhance={
          <EnhanceButton
            product={PRODUCT}
            kind={mode === "text" ? "text_to_video" : "image_to_video"}
            value={prompt}
            uploadId={pic.picture?.uploadId}
            needsPicture={mode === "image"}
            maxChars={MAX_PROMPT}
            disabled={busy || pic.status === "uploading"}
            onChange={setPrompt}
          />
        }
        onSubmit={submit}
      />

      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>Length</legend>
        <div className={chips}>
          {LENGTHS.map((l) => (
            <Chip
              key={l.seconds}
              aria-pressed={seconds === l.seconds}
              onClick={() => setSeconds(l.seconds)}
            >
              {l.label}
            </Chip>
          ))}
        </div>
      </fieldset>

      {mode === "text" ? (
        <fieldset className={cn(field, "m-0 border-0 p-0")}>
          <legend className={cn(fieldLabel, "mb-1.5")}>Shape</legend>
          <div className={chips}>
            {SHAPES.map((s) => (
              <Chip key={s.id} aria-pressed={shape === s.id} onClick={() => setShape(s.id)}>
                {s.label} <span className="opacity-70">{s.hint}</span>
              </Chip>
            ))}
          </div>
        </fieldset>
      ) : null}

      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" size="lg" disabled={!valid || busy}>
          {busy ? <Spinner /> : null}
          Make my video
        </Button>
        <span className="text-muted-foreground">
          Takes {wait}. You can explore the site while it's made.
          {mode === "image" ? " The clip keeps the shape of your picture." : ""}
        </span>
      </div>
    </form>
  );
}
