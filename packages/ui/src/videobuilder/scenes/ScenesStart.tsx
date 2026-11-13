"use client";
// The first screen of Motion graphics (ADR-0096, mockup "New project"): what do you want to promote?
// The assistant writes a first version in the editor; the person changes it from there.
import type { BuilderShape, TemplateCatalogue } from "@wasifyai/client";
import { useState } from "react";
import { Button } from "../../components/button";
import { Chip } from "../../components/chip";
import { Segmented } from "../../components/segmented";

const SHAPES: { value: BuilderShape; label: string }[] = [
  { value: "portrait", label: "9:16" },
  { value: "landscape", label: "16:9" },
  { value: "feed", label: "4:5" },
  { value: "square", label: "1:1" },
];

export function ScenesStart({
  catalogue,
  onBrief,
  onStart,
  onEmpty,
  onOneGraphic,
  disabled,
}: {
  catalogue: TemplateCatalogue | null;
  onBrief: (brief: string, shape: BuilderShape, picture?: File) => void;
  /** A set of scenes with words to replace, and what the assistant is asked to fill them with. */
  onStart: (start: string, shape: BuilderShape, brief?: string, picture?: File) => void;
  onEmpty: (shape: BuilderShape) => void;
  onOneGraphic: (template: string) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const [shape, setShape] = useState<BuilderShape>("portrait");
  const [start, setStart] = useState<string | null>(null);
  const [picture, setPicture] = useState<File | null>(null);
  const brief = text.trim();
  const starting = catalogue?.starts?.find((s) => s.id === start);
  return (
    <section
      aria-label="New project"
      className="mx-auto grid w-full max-w-3xl gap-5 p-[clamp(1rem,4vw,2.5rem)]"
    >
      <h1 className="m-0 text-center font-semibold text-step-2 tracking-tight">
        What do you want to promote?
      </h1>
      <div className="grid gap-3 rounded-xl border bg-card p-3 shadow-sm">
        <textarea
          aria-label="Describe your video"
          rows={3}
          className="w-full resize-none bg-transparent p-1 text-base outline-none"
          placeholder="A 20 second vertical ad for our cold brew. Calm, for people who hate mornings."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <label className="flex w-fit cursor-pointer items-center gap-2 rounded-full border px-3 py-1 text-xs hover:bg-muted">
          {picture ? picture.name : "Add a picture of it"}
          <input
            type="file"
            className="sr-only"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => setPicture(e.target.files?.[0] ?? null)}
          />
        </label>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Segmented
            size="sm"
            label="Shape"
            value={shape}
            onValueChange={(v) => setShape(v as BuilderShape)}
            options={SHAPES}
          />
          <span className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={disabled}
              onClick={() => onEmpty(shape)}
            >
              Start empty
            </Button>
            <Button
              type="button"
              disabled={disabled || (!brief && !starting)}
              onClick={() =>
                starting
                  ? onStart(starting.id, shape, brief || undefined, picture ?? undefined)
                  : onBrief(brief, shape, picture ?? undefined)
              }
            >
              {starting && !brief ? `Start from ${starting.title}` : "Make a first version"}
            </Button>
          </span>
        </div>
        <p className="m-0 text-muted-foreground text-xs">
          {starting && !brief
            ? `${starting.description} The words are there for you to replace.`
            : "The assistant writes the scenes and you change them. No video is made yet."}
        </p>
      </div>
      <div className="grid gap-1.5">
        <h2 className="m-0 font-medium text-sm">Or start from</h2>
        <div className="flex flex-wrap gap-2">
          {catalogue?.starts?.map((s) => (
            <Chip
              key={s.id}
              aria-pressed={start === s.id}
              onClick={() => setStart((now) => (now === s.id ? null : s.id))}
            >
              {s.title}
            </Chip>
          ))}
        </div>
      </div>
      <div className="grid gap-1.5">
        <h2 className="m-0 font-medium text-sm">Or just one graphic</h2>
        <div className="flex flex-wrap gap-2">
          {catalogue?.templates.map((t) => (
            <Chip key={t.id} onClick={() => onOneGraphic(t.id)}>
              {t.title}
            </Chip>
          ))}
        </div>
      </div>
    </section>
  );
}
