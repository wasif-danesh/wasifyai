"use client";

import { EnhanceButton } from "@/components/EnhanceButton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import type { SongInput } from "@/lib/run-client";
import { chips, counter, field, fieldLabel, hint, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import { type FormEvent, type KeyboardEvent, useId, useState } from "react";

export const MAX_IDEA = 500;
const GENRES = [
  "Pop",
  "Rock",
  "Hip hop",
  "Electronic",
  "Folk",
  "Jazz",
  "Lo-fi",
  "Country",
  "R&B",
  "Metal",
];
const MOODS = ["Upbeat", "Mellow", "Dreamy", "Romantic", "Dark", "Nostalgic", "Playful", "Angry"];
const EXAMPLES = [
  "A rainy night in Tokyo: neon reflections and a quiet walk home",
  "A funny song about my cat who hates Mondays",
  "An anthem for finally finishing my first marathon",
  "A lullaby for a very sleepy dinosaur",
];

function Choice({
  legend,
  options,
  value,
  onChange,
}: {
  legend: string;
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <fieldset className={field}>
      <legend className={cn(fieldLabel, "mb-1.5")}>
        {legend} <span className="font-normal text-muted-foreground">(optional)</span>
      </legend>
      <div className={chips}>
        {options.map((o) => (
          <Chip key={o} aria-pressed={value === o} onClick={() => onChange(value === o ? "" : o)}>
            {o}
          </Chip>
        ))}
      </div>
    </fieldset>
  );
}

export function IdeaForm({
  onSubmit,
  initial,
  busy = false,
}: {
  onSubmit: (input: SongInput) => void;
  initial?: SongInput;
  busy?: boolean;
}) {
  const id = useId();
  const [idea, setIdea] = useState(initial?.idea ?? "");
  const [genre, setGenre] = useState(initial?.genre ?? "");
  const [mood, setMood] = useState(initial?.mood ?? "");
  const trimmed = idea.trim();
  const valid = trimmed.length > 0 && idea.length <= MAX_IDEA;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!valid || busy) return;
    onSubmit({ idea: trimmed, ...(genre && { genre }), ...(mood && { mood }) });
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
  }

  return (
    <form className={cn(panel, "gap-6")} onSubmit={submit}>
      <div className={field}>
        <Label htmlFor={`${id}-idea`} className={fieldLabel}>
          What's the song about?
        </Label>
        <Textarea
          id={`${id}-idea`}
          className="min-h-28 max-h-[28rem] text-base leading-normal"
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          onKeyDown={onKey}
          placeholder="A rainy night in Tokyo, neon lights and a quiet walk home…"
          rows={3}
          aria-describedby={`${id}-hint`}
          aria-invalid={idea.length > MAX_IDEA}
          autoFocus
        />
        <div className="flex flex-wrap items-center gap-3">
          <span className={cn(hint, "min-w-0 grow basis-[12rem]")} id={`${id}-hint`}>
            Describe a story, a feeling or a scene. Press Ctrl or ⌘ + Enter to start.
          </span>
          <EnhanceButton
            product="wasifyai-music"
            kind="song_idea"
            value={idea}
            maxChars={MAX_IDEA}
            disabled={busy}
            onChange={setIdea}
          />
          <span className={counter(idea.length > MAX_IDEA * 0.9)}>
            {idea.length}/{MAX_IDEA}
          </span>
        </div>
        <fieldset className={cn(chips, "m-0 border-0 p-0")}>
          <legend className="sr-only">Example ideas</legend>
          {EXAMPLES.map((ex) => (
            <Chip key={ex} onClick={() => setIdea(ex)}>
              {ex.split(":")[0]}
            </Chip>
          ))}
        </fieldset>
      </div>

      <Choice legend="Genre" options={GENRES} value={genre} onChange={setGenre} />
      <Choice legend="Mood" options={MOODS} value={mood} onChange={setMood} />

      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" size="lg" disabled={!valid || busy}>
          {busy ? <Spinner /> : null}
          Write my song
        </Button>
        <span className="text-muted-foreground">
          You'll review the lyrics before any music is made.
        </span>
      </div>
    </form>
  );
}
