"use client";
// The first thing Motion graphics shows: say what to make in your own words, perhaps with a CSV file,
// and the form opens filled in. Nothing is made from here; the person checks the form first.

import type { BuilderShape, DraftRequest } from "@wasifyai/client";
import { ArrowRight, Paperclip, X } from "lucide-react";
import { type ReactNode, useId, useRef, useState } from "react";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { Notice } from "../components/notice";
import { hint } from "../styles";

const MAX_FILE_BYTES = 40_000;

export const EXAMPLES: { label: string; about: string; text: string; sample: ReactNode }[] = [
  {
    label: "Animated title",
    about: "A big title with a line under it.",
    text: 'Title "Launch day" with the line "Wasify AI is here"',
    sample: <span className="font-semibold font-serif text-step-1">Launch day</span>,
  },
  {
    label: "Quote",
    about: "A quotation and who said it.",
    text: 'Quote: "The best way to predict the future is to invent it." by Alan Kay',
    sample: <span className="font-serif italic">“Invent the future.”</span>,
  },
  {
    label: "Bar chart",
    about: "Numbers as bars that grow.",
    text: 'Bar chart "Sales by region": North 120, South 95, East 150',
    sample: (
      <svg width="72" height="40" viewBox="0 0 72 40" aria-hidden="true" className="text-primary">
        <rect x="4" y="16" width="14" height="22" rx="2" fill="currentColor" opacity=".5" />
        <rect x="26" y="4" width="14" height="34" rx="2" fill="currentColor" />
        <rect x="48" y="22" width="14" height="16" rx="2" fill="currentColor" opacity=".5" />
      </svg>
    ),
  },
  {
    label: "Lower third",
    about: "A name and role over a video.",
    text: 'Lower third for "Maya Chen", Head of Design',
    sample: (
      <span className="border-primary border-s-[3px] ps-2 text-start leading-tight">
        <b className="block text-step--1">Maya Chen</b>
        <span className="text-muted-foreground text-xs">Head of Design</span>
      </span>
    ),
  },
  {
    label: "Captions",
    about: "Lines of text, one after another.",
    text: 'Captions: "Welcome to the show", then "Today we talk about AI", 4 seconds each',
    sample: (
      <span className="rounded bg-foreground/80 px-2 py-0.5 text-background text-sm">
        Welcome to the show
      </span>
    ),
  },
];

const SHAPES: { id: BuilderShape; label: string; w: number; h: number }[] = [
  { id: "landscape", label: "16:9", w: 16, h: 9 },
  { id: "portrait", label: "9:16", w: 9, h: 16 },
  { id: "square", label: "1:1", w: 12, h: 12 },
  { id: "feed", label: "4:5", w: 12, h: 15 },
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
  const id = useId();
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
    <section aria-label="What to make" className="grid min-w-0 content-start gap-5">
      <div className="grid gap-1">
        <h2 className="m-0 font-semibold text-base">What should we make?</h2>
        <p className="text-muted-foreground">
          Say it in your own words. You check the form before anything is made.
        </p>
      </div>

      <div className="grid gap-3 rounded-2xl border bg-surface p-3.5 shadow-card focus-within:ring-[3px] focus-within:ring-ring/40">
        <textarea
          ref={box}
          aria-label="Describe what to make"
          rows={3}
          value={text}
          maxLength={2000}
          placeholder='Lower third for "Maya Chen", Head of Design'
          className="min-h-20 w-full resize-none bg-transparent text-base outline-none placeholder:text-muted-foreground"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        {file ? (
          <div className="flex min-w-0 items-center gap-2 text-sm">
            <Paperclip className="size-4 shrink-0" aria-hidden="true" />
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
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
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
              <Paperclip className="mr-1 inline size-3.5" aria-hidden="true" />
              Attach a CSV
            </Chip>
            <fieldset
              aria-label="Shape"
              className="inline-flex gap-0.5 rounded-lg border bg-muted p-0.5"
            >
              {SHAPES.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  aria-pressed={shape === s.id}
                  aria-label={s.label}
                  title={s.label}
                  onClick={() => setShape(shape === s.id ? null : s.id)}
                  className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-muted-foreground text-sm aria-pressed:bg-surface aria-pressed:text-foreground aria-pressed:shadow-sm"
                >
                  <span
                    aria-hidden="true"
                    className="inline-block rounded-xs border-[1.5px] border-current"
                    style={{ width: s.w, height: s.h }}
                  />
                  <span aria-hidden="true" className="hidden sm:inline">
                    {s.label}
                  </span>
                </button>
              ))}
            </fieldset>
          </div>
          <Button type="button" className="max-sm:w-full" disabled={!ready || busy} onClick={send}>
            Fill in the form <ArrowRight className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {busy ? <output className={hint}>Reading your request…</output> : null}
      {fileError ? (
        <Notice tone="error" title="That file cannot be used">
          {fileError}
        </Notice>
      ) : null}

      <h3 className="text-muted-foreground text-sm">Or start from an example</h3>
      <div className="-mt-3 grid grid-cols-2 gap-2.5 md:grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))]">
        {EXAMPLES.map((e, i) => (
          <button
            key={e.label}
            type="button"
            aria-labelledby={`${id}-${i}-t`}
            aria-describedby={`${id}-${i}-d`}
            onClick={() => {
              setText(e.text);
              box.current?.focus();
            }}
            className="grid min-w-0 content-start gap-2 rounded-xl border bg-surface p-2.5 text-start transition-colors hover:border-primary/50"
          >
            <span
              aria-hidden="true"
              className="hidden h-16 place-items-center overflow-hidden rounded-lg bg-muted md:grid"
            >
              {e.sample}
            </span>
            <b id={`${id}-${i}-t`} className="font-semibold">
              {e.label}
            </b>
            <span id={`${id}-${i}-d`} className="text-muted-foreground text-sm leading-snug">
              {e.about}
            </span>
          </button>
        ))}
      </div>
      <button
        type="button"
        className="w-fit text-muted-foreground text-sm underline underline-offset-4 hover:text-foreground"
        onClick={onForm}
      >
        Or fill in the form yourself
      </button>
    </section>
  );
}
