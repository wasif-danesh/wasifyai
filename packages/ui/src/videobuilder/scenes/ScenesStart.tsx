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
  { value: "square", label: "1:1" },
];

// what each starting point adds to the brief; MX7 makes these ready-made sets of scenes
const STARTS = [
  ["Product promo", "A short promo that shows a product and why it matters."],
  ["Launch announcement", "An announcement that something new is here."],
  ["Sale or offer", "A short video about an offer, clear about what it is."],
  ["Customer words", "A short video built around what a customer said."],
  ["Feature explainer", "A short video that explains one feature, step by step."],
  ["Before and after", "A short video that shows the difference, before and after."],
  ["Social post", "One idea, short and loud, for a social post."],
] as const;

export function ScenesStart({
  catalogue,
  onBrief,
  onEmpty,
  onOneGraphic,
  disabled,
}: {
  catalogue: TemplateCatalogue | null;
  onBrief: (brief: string, shape: BuilderShape) => void;
  onEmpty: (shape: BuilderShape) => void;
  onOneGraphic: (template: string) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const [shape, setShape] = useState<BuilderShape>("portrait");
  const [start, setStart] = useState<string | null>(null);
  const chosen = STARTS.find(([name]) => name === start)?.[1] ?? "";
  const brief = [chosen, text.trim()].filter(Boolean).join(" ");
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
              disabled={disabled || !brief}
              onClick={() => onBrief(brief, shape)}
            >
              Make a first version
            </Button>
          </span>
        </div>
        <p className="m-0 text-muted-foreground text-xs">
          The assistant writes the scenes and you change them. No video is made yet.
        </p>
      </div>
      <div className="grid gap-1.5">
        <h2 className="m-0 font-medium text-sm">Or start from</h2>
        <div className="flex flex-wrap gap-2">
          {STARTS.map(([name]) => (
            <Chip
              key={name}
              aria-pressed={start === name}
              onClick={() => setStart((s) => (s === name ? null : name))}
            >
              {name}
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
