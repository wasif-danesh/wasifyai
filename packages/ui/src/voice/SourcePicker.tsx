"use client";

import type { AudioSource, Speech, Track } from "@wasifyai/client";
import { useRef } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Player } from "../components/player";
import { Select } from "../components/select";
import { clock } from "./format";

export type Library = { tracks: Track[]; speeches: Speech[] };

/** The recording a source points at, as the screens show it. */
export function pickedOf(source: AudioSource | null, library: Library | null) {
  if (!source || !library) return null;
  if (source.kind === "track") {
    const t = library.tracks.find((x) => x.id === source.id);
    return t ? { title: t.title, seconds: t.seconds, url: t.audio_url } : null;
  }
  const s = library.speeches.find((x) => x.id === source.id);
  return s ? { title: s.text.slice(0, 60), seconds: s.seconds, url: s.audio_url } : null;
}

/**
 * Choose a recording from the library (your music and recordings, and speech you made) or add one from this
 * computer, and hear it: the one way every voice tool asks for a recording (ADR-0093, the app's own controls).
 */
export function SourcePicker({
  id,
  label,
  library,
  value,
  onChange,
  onAdd,
  disabled,
}: {
  id: string;
  label: string;
  library: Library;
  value: AudioSource | null;
  onChange: (source: AudioSource | null) => void;
  /** add a file from this computer (it joins Your music) */
  onAdd?: (file: File) => void;
  disabled?: boolean;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const picked = pickedOf(value, library);
  const options = [
    ...(library.tracks.length > 0
      ? [
          {
            label: "Your music and recordings",
            options: library.tracks.map((t) => ({
              value: `track:${t.id}`,
              label: `${t.title} (${clock(t.seconds)})`,
            })),
          },
        ]
      : []),
    ...(library.speeches.length > 0
      ? [
          {
            label: "Speech you made",
            options: library.speeches.map((s) => ({
              value: `speech:${s.id}`,
              label: `${s.text.slice(0, 50)} (${clock(s.seconds)})`,
            })),
          },
        ]
      : []),
  ];
  return (
    <div className="grid gap-2">
      <Label htmlFor={id} className="font-semibold text-ui-lg">
        {label}
      </Label>
      <Select
        id={id}
        value={value ? `${value.kind}:${value.id}` : undefined}
        placeholder={options.length ? "Choose…" : "Nothing in the library yet"}
        disabled={disabled || options.length === 0}
        options={options}
        onValueChange={(v) => {
          const [kind, ...rest] = v.split(":");
          onChange(kind === "track" || kind === "speech" ? { kind, id: rest.join(":") } : null);
        }}
      />
      {onAdd ? (
        <>
          <input
            ref={picker}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.caf,.aiff"
            className="sr-only"
            aria-label="Add a recording from this computer"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onAdd(f);
            }}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="justify-self-start"
            disabled={disabled}
            onClick={() => picker.current?.click()}
          >
            Add a recording
          </Button>
        </>
      ) : null}
      {picked ? <Player src={picked.url} title={picked.title} duration={picked.seconds} /> : null}
    </div>
  );
}
