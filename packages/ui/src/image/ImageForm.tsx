"use client";

import type { Mode, RunClient } from "@wasifyai/client";
import { type FormEvent, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { ModeTabs, PromptField } from "../components/create";
import { EnhanceButton } from "../components/enhance-button";
import { PictureInput } from "../components/picture-input";
import { Spinner } from "../components/spinner";
import { type Picture, usePicture } from "../hooks/use-picture";
import { usePictureEvents } from "../hooks/use-picture-events";
import { chips, field, fieldLabel, panel } from "../styles";

export const MAX_PROMPT = 500;
const PRODUCT = "wasifyai-image";

export const SIZES = [
  { id: "square", label: "Square", hint: "1:1" },
  { id: "landscape", label: "Landscape", hint: "4:3" },
  { id: "portrait", label: "Portrait", hint: "3:4" },
  { id: "wide", label: "Wide", hint: "16:9" },
  { id: "tall", label: "Tall", hint: "9:16" },
] as const;

const EXAMPLES: Record<Mode, string[]> = {
  text: [
    "A lighthouse on a cliff at sunrise, soft watercolour",
    "A cosy reading nook with a sleeping cat, warm light",
    "A paper-craft city at night, glowing windows",
  ],
  image: [
    "Make it look like a watercolour painting",
    "Change the background to a snowy forest",
    "Turn the daytime scene into a golden-hour evening",
  ],
};

/** What the form hands over: the picture is already uploaded (ADR-0039), so a run needs only its key. */
export type ImageFormValue = {
  mode: Mode;
  prompt: string;
  size: string;
  picture: Picture | null;
};

export function ImageForm({
  client,
  onSubmit,
  initial,
  busy = false,
}: {
  /** The app's client: uploads the picture and enhances the prompt. Keep it the same object. */
  client: Pick<RunClient, "uploadImage" | "deleteUpload" | "enhancePrompt">;
  onSubmit: (value: ImageFormValue) => void;
  initial?: Partial<Pick<ImageFormValue, "mode" | "prompt" | "size">>;
  busy?: boolean;
}) {
  const id = useId();
  const [mode, setMode] = useState<Mode>(initial?.mode ?? "text");
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [size, setSize] = useState(initial?.size ?? "square");
  const pic = usePicture(PRODUCT, client);
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

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!valid || busy) return;
    if (mode === "image") pic.handOver(); // the run owns the picture from here
    onSubmit({
      mode,
      prompt: trimmed,
      size,
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
        label={mode === "text" ? "What should the image show?" : "What should change?"}
        value={prompt}
        onChange={setPrompt}
        placeholder={EXAMPLES[mode][0] ?? ""}
        hintText={"Press Ctrl or ⌘ + Enter to start."}
        max={MAX_PROMPT}
        examples={EXAMPLES[mode]}
        exampleLabel={(ex) => ex.split(",")[0] ?? ex}
        enhance={
          <EnhanceButton
            enhance={client.enhancePrompt}
            product={PRODUCT}
            kind={mode === "text" ? "text_to_image" : "edit_image"}
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

      {mode === "text" ? (
        <fieldset className={cn(field, "m-0 border-0 p-0")}>
          <legend className={cn(fieldLabel, "mb-1.5")}>Shape</legend>
          <div className={chips}>
            {SIZES.map((s) => (
              <Chip key={s.id} aria-pressed={size === s.id} onClick={() => setSize(s.id)}>
                {s.label} <span className="opacity-70">{s.hint}</span>
              </Chip>
            ))}
          </div>
        </fieldset>
      ) : null}

      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" size="lg" disabled={!valid || busy}>
          {busy ? <Spinner /> : null}
          Make my image
        </Button>
        <span className="text-muted-foreground">
          {mode === "image"
            ? "The result keeps the size of your picture."
            : "Takes about a minute."}
        </span>
      </div>
    </form>
  );
}
