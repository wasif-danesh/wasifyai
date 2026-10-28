"use client";

import type { SavedVoice, Speech, VoiceInfo } from "@wasifyai/client";
import { CheckIcon, PauseIcon, PlayIcon, Plus, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Spinner } from "../components/spinner";
import { groupVoices } from "./format";

/** The voice a speech is spoken in: one that comes with the model, or one the person saved. */
export type VoiceChoice = { kind: "builtin"; id: string } | { kind: "saved"; id: string };

type Row = {
  key: string;
  choice: VoiceChoice;
  name: string;
  detail: string;
  /** a recording of this voice to play now, when there is one */
  sample: string | null;
};

const SEARCH_FROM = 9;

/**
 * Choose a voice by hearing it (ADR-0093, stage U5): the person's own voices first, then the model's, each with
 * a play button. A voice nobody has heard yet offers "Hear a sample", which speaks one short line (the Voices
 * screen does the same). "Make a voice" at the end opens the way to describe or copy one.
 */
export function VoicesPanel({
  builtIn,
  saved,
  value,
  onChange,
  speeches,
  modelId,
  onSample,
  onMakeVoice,
  disabled,
}: {
  /** the voices of the chosen model */
  builtIn: VoiceInfo[];
  saved: SavedVoice[];
  value: VoiceChoice | null;
  onChange: (choice: VoiceChoice) => void;
  /** what was spoken before: a voice heard before plays that */
  speeches: Speech[];
  modelId: string | null;
  /** speak a short line in this voice and give back where to play it, or null */
  onSample?: (choice: VoiceChoice) => Promise<string | null>;
  onMakeVoice?: () => void;
  disabled?: boolean;
}) {
  const group = useId();
  const [query, setQuery] = useState("");
  const [playing, setPlaying] = useState<string | null>(null);
  const [making, setMaking] = useState<string | null>(null);
  const [made, setMade] = useState<Record<string, string>>({});
  const audio = useRef<HTMLAudioElement>(null);

  const rows = useMemo(() => {
    const own: Row[] = saved.map((v) => ({
      key: `saved:${v.id}`,
      choice: { kind: "saved", id: v.id },
      name: v.name,
      detail: v.kind === "design" ? "Described" : "Copied from a recording",
      sample:
        speeches.find((s) => s.saved_voice_id === v.id)?.audio_url ??
        (v.kind === "clone" ? (v.reference_url ?? null) : null),
    }));
    const groups = groupVoices(builtIn).map((g) => ({
      label: g.label,
      rows: g.voices.map<Row>((v) => ({
        key: `builtin:${v.id}`,
        choice: { kind: "builtin", id: v.id },
        name: v.label,
        detail: v.gender ? `${v.gender.charAt(0).toUpperCase()}${v.gender.slice(1)}` : "",
        sample:
          speeches.find(
            (s) => !s.saved_voice_id && s.voice === v.id && (!modelId || s.model_id === modelId),
          )?.audio_url ?? null,
      })),
    }));
    return { own, groups };
  }, [saved, builtIn, speeches, modelId]);

  const q = query.trim().toLowerCase();
  const match = (r: Row) => !q || `${r.name} ${r.detail}`.toLowerCase().includes(q);
  const count = rows.own.length + rows.groups.reduce((n, g) => n + g.rows.length, 0);
  const current = value ? `${value.kind}:${value.id}` : null;

  // the chosen voice in view when the list opens
  // biome-ignore lint/correctness/useExhaustiveDependencies: only when the list is first filled
  useEffect(() => {
    if (!current) return;
    document
      .querySelector(`[data-voice="${CSS.escape(current)}"]`)
      ?.scrollIntoView?.({ block: "nearest" });
  }, [count]);

  function play(key: string, url: string) {
    const el = audio.current;
    if (!el) return;
    if (playing === key) {
      el.pause();
      return;
    }
    el.src = url;
    void el.play()?.catch(() => setPlaying(null));
    setPlaying(key);
  }

  async function sample(r: Row) {
    if (!onSample || making) return;
    setMaking(r.key);
    try {
      const url = await onSample(r.choice);
      if (url) {
        setMade((m) => ({ ...m, [r.key]: url }));
        play(r.key, url);
      }
    } finally {
      setMaking(null);
    }
  }

  const row = (r: Row) => {
    const chosen = current === r.key;
    const url = made[r.key] ?? r.sample;
    return (
      <li
        key={r.key}
        data-voice={r.key}
        className={cn(
          "flex items-center gap-2 rounded-md px-2 py-1.5",
          chosen ? "bg-accent" : "hover:bg-accent/60",
        )}
      >
        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-sm has-[:disabled]:cursor-default has-[:disabled]:opacity-60 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring">
          <input
            type="radio"
            name={group}
            className="sr-only"
            checked={chosen}
            disabled={disabled}
            onChange={() => onChange(r.choice)}
          />
          <span
            aria-hidden="true"
            className={cn(
              "grid size-4 shrink-0 place-items-center rounded-full border",
              chosen && "border-primary bg-primary text-primary-foreground",
            )}
          >
            {chosen ? <CheckIcon className="size-3" /> : null}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm">{r.name}</span>
            {r.detail ? (
              <span className="block truncate text-muted-foreground text-xs">{r.detail}</span>
            ) : null}
          </span>
        </label>
        {url ? (
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            aria-label={playing === r.key ? `Stop ${r.name}` : `Play ${r.name}`}
            onClick={() => play(r.key, url)}
          >
            {playing === r.key ? <PauseIcon aria-hidden="true" /> : <PlayIcon aria-hidden="true" />}
          </Button>
        ) : onSample ? (
          <Button
            type="button"
            size="xs"
            variant="ghost"
            className="shrink-0 text-muted-foreground"
            disabled={disabled || making !== null}
            aria-label={`Hear a sample of ${r.name}`}
            onClick={() => void sample(r)}
          >
            {making === r.key ? <Spinner /> : null}
            {making === r.key ? "Making…" : "Hear it"}
          </Button>
        ) : null}
      </li>
    );
  };

  const own = rows.own.filter(match);
  return (
    <section className="grid gap-2" aria-label="Voice">
      <h2 className="m-0 font-semibold text-ui-lg">Voice</h2>
      {/* biome-ignore lint/a11y/useMediaCaption: a voice sample; the voice's name is beside it */}
      <audio
        ref={audio}
        className="hidden"
        onPause={() => setPlaying(null)}
        onEnded={() => setPlaying(null)}
      />
      {count >= SEARCH_FROM ? (
        <label className="relative">
          <span className="sr-only">Find a voice</span>
          <Search className="-translate-y-1/2 pointer-events-none absolute start-2.5 top-1/2 size-4 text-muted-foreground" />
          <input
            type="search"
            value={query}
            placeholder="Find a voice by name or language"
            onChange={(e) => setQuery(e.target.value)}
            className="h-9 w-full rounded-md border border-input bg-transparent ps-8 pe-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
        </label>
      ) : null}
      <fieldset
        aria-label="Voices"
        className="m-0 grid max-h-72 gap-3 overflow-auto rounded-md border p-1.5"
      >
        {own.length > 0 ? (
          <div className="grid gap-0.5">
            <h3 className="m-0 px-2 pt-1 font-medium text-muted-foreground text-xs">Your voices</h3>
            <ul className="m-0 grid list-none gap-0.5 p-0">{own.map(row)}</ul>
          </div>
        ) : null}
        {rows.groups.map((g) => {
          const shown = g.rows.filter(match);
          return shown.length > 0 ? (
            <div key={g.label} className="grid gap-0.5">
              <h3 className="m-0 px-2 pt-1 font-medium text-muted-foreground text-xs">{g.label}</h3>
              <ul className="m-0 grid list-none gap-0.5 p-0">{shown.map(row)}</ul>
            </div>
          ) : null;
        })}
        {count === 0 ? (
          <p className="m-0 px-2 py-3 text-muted-foreground text-sm">
            This model speaks in one voice of its own.
          </p>
        ) : q &&
          own.length + rows.groups.reduce((n, g) => n + g.rows.filter(match).length, 0) === 0 ? (
          <p className="m-0 px-2 py-3 text-muted-foreground text-sm">No voice matches “{query}”.</p>
        ) : null}
      </fieldset>
      {onMakeVoice ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="justify-self-start"
          disabled={disabled}
          onClick={onMakeVoice}
        >
          <Plus aria-hidden="true" /> Make a voice
        </Button>
      ) : null}
    </section>
  );
}
