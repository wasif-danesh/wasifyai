"use client";
// The first thing Video Builder shows: say what to make in your own words, perhaps with a CSV file,
// and the form opens filled in. Nothing is made from here; the person checks the form first.

import type { BuilderShape, DraftRequest } from "@wasifyai/client";
import { ArrowUp, Paperclip, X } from "lucide-react";
import { useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { Notice } from "../components/notice";
import { chips, hint } from "../styles";

const MAX_FILE_BYTES = 40_000;

export const EXAMPLES: { label: string; text: string }[] = [
  {
    label: "Animated title",
    text: 'Title "Launch day" with the line "Wasify AI is here"',
  },
  {
    label: "Quote",
    text: 'Quote: "The best way to predict the future is to invent it." by Alan Kay',
  },
  { label: "Bar chart", text: 'Bar chart "Sales by region": North 120, South 95, East 150' },
  { label: "Lower third", text: 'Lower third for "Maya Chen", Head of Design' },
  {
    label: "Captions",
    text: 'Captions: "Welcome to the show", then "Today we talk about AI", 4 seconds each',
  },
];

const SHAPES: { id: BuilderShape; label: string }[] = [
  { id: "landscape", label: "16:9" },
  { id: "portrait", label: "9:16" },
  { id: "square", label: "1:1" },
];

export function PromptBox({
  busy,
  onSend,
  onForm,
}: {
  busy: boolean;
  onSend: (request: DraftRequest) => void;
  onForm: () => void;
}) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<{ name: string; text: string } | null>(null);
  const [shape, setShape] = useState<BuilderShape | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const ready = text.trim().length > 0 || file !== null;

  async function attach(chosen: File | undefined) {
    if (!chosen) return;
    setFileError(null);
    if (chosen.size > MAX_FILE_BYTES) {
      setFileError("That file is too big for a chart. Use a CSV under 40 KB.");
      return;
    }
    setFile({ name: chosen.name, text: await chosen.text() });
  }

  function send() {
    if (!ready || busy) return;
    onSend({
      prompt: text.trim(),
      attachment: file ?? undefined,
      shape: shape ?? undefined,
    });
  }

  return (
    <section aria-label="What to make" className="grid justify-items-center gap-5 py-2">
      <div className="grid gap-1 text-center">
        <h2 className="font-serif text-step-3">What should we make?</h2>
        <p className="text-muted-foreground">
          Say it in your own words. You check the form before anything is made.
        </p>
      </div>

      <div className="grid w-full max-w-3xl gap-3 rounded-2xl border bg-surface p-3.5 shadow-card">
        <textarea
          ref={box}
          aria-label="Describe what to make"
          rows={3}
          value={text}
          maxLength={2000}
          placeholder='Lower third for "Maya Chen", Head of Design'
          className="w-full resize-none bg-transparent text-base outline-none placeholder:text-muted-foreground"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        {file ? (
          <div className="flex items-center gap-2 text-sm">
            <Paperclip className="size-4" aria-hidden="true" />
            <span className="truncate">{file.name}</span>
            <button
              type="button"
              aria-label={`Remove ${file.name}`}
              className="rounded p-0.5 hover:bg-accent"
              onClick={() => setFile(null)}
            >
              <X className="size-4" />
            </button>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className={cn(chips, "items-center")}>
            <input
              ref={picker}
              type="file"
              accept=".csv,.tsv,.txt,text/csv,text/plain"
              hidden
              aria-label="Choose a CSV file"
              onChange={(e) => {
                void attach(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            <Chip type="button" onClick={() => picker.current?.click()}>
              <Paperclip className="size-3.5" aria-hidden="true" /> Attach a CSV
            </Chip>
            {SHAPES.map((s) => (
              <Chip
                key={s.id}
                aria-pressed={shape === s.id}
                onClick={() => setShape(shape === s.id ? null : s.id)}
              >
                {s.label}
              </Chip>
            ))}
          </div>
          <Button
            type="button"
            size="icon"
            aria-label="Fill in the form"
            disabled={!ready || busy}
            onClick={send}
          >
            <ArrowUp className="size-4" />
          </Button>
        </div>
      </div>

      {busy ? <output className={hint}>Reading your request…</output> : null}
      {fileError ? (
        <Notice tone="error" title="That file cannot be used">
          {fileError}
        </Notice>
      ) : null}

      <div className={cn(chips, "justify-center")}>
        {EXAMPLES.map((e) => (
          <Chip
            key={e.label}
            onClick={() => {
              setText(e.text);
              box.current?.focus();
            }}
          >
            {e.label}
          </Chip>
        ))}
      </div>
      <button
        type="button"
        className="text-muted-foreground text-sm underline underline-offset-4 hover:text-foreground"
        onClick={onForm}
      >
        Or fill in the form yourself
      </button>
    </section>
  );
}
