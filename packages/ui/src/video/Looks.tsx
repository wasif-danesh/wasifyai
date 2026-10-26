"use client";

import { useId, useState } from "react";
import { hint } from "../styles";

/** A look the person taught the video model (Train models): the file it is kept in, its name and its magic word. */
export type VideoLook = { name: string; title: string; word: string };

/** A look chosen for a clip, with its strength. */
export type LookChoice = { name: string; weight: number };

export const MAX_LOOKS = 2;
export const LOOK_MIN = 0.1;
export const LOOK_MAX = 2.5;
/** What the first video taught on this Mac needed at the app's guidance (docs/spikes/video-training-tv0.md). */
export const LOOK_DEFAULT = 1.5;

/** The prompt with the magic word of each chosen look in it: a look only shows when its word is written. */
export function withWords(prompt: string, looks: VideoLook[], chosen: LookChoice[]): string {
  let text = prompt;
  for (const c of chosen) {
    const word = looks.find((l) => l.name === c.name)?.word;
    if (word && !text.toLowerCase().includes(word.toLowerCase())) text = `${word}, ${text}`;
  }
  return text;
}

/**
 * "My looks": the looks the person taught the video model, each a switch with its own strength. Closed by
 * default so the form stays as it was; shown only when there is something to choose.
 */
export function Looks({
  looks,
  chosen,
  onChange,
}: {
  looks: VideoLook[];
  chosen: LookChoice[];
  onChange: (next: LookChoice[]) => void;
}) {
  const [open, setOpen] = useState(chosen.length > 0);
  const group = useId();
  if (looks.length === 0) return null;
  const toggle = (name: string) =>
    onChange(
      chosen.some((c) => c.name === name)
        ? chosen.filter((c) => c.name !== name)
        : [...chosen, { name, weight: LOOK_DEFAULT }],
    );
  const strength = (name: string, weight: number) =>
    onChange(chosen.map((c) => (c.name === name ? { ...c, weight } : c)));
  return (
    <section className="grid gap-2" aria-label="My looks">
      <button
        type="button"
        className="flex items-center justify-between gap-3 text-start font-semibold"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span>
          My looks{" "}
          <span className="font-normal text-muted-foreground">
            {chosen.length ? `(${chosen.length} chosen)` : "(optional)"}
          </span>
        </span>
        <span aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      {open ? (
        <div className="grid gap-2">
          <p className={hint}>
            A look is a character, style or motion you taught the video model. Choose up to{" "}
            {MAX_LOOKS}. Its magic word is added to your prompt if it is missing. About 1.5 is a
            good strength; above 2 can look rough.
          </p>
          <ul className="m-0 grid list-none gap-2 p-0">
            {looks.map((l) => {
              const on = chosen.find((c) => c.name === l.name);
              const id = `${group}-${l.name}`;
              return (
                <li key={l.name} className="grid gap-1.5 rounded-lg border px-3 py-2">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={Boolean(on)}
                      disabled={!on && chosen.length >= MAX_LOOKS}
                      onChange={() => toggle(l.name)}
                    />
                    <span className="min-w-0 flex-1 truncate">{l.title}</span>
                    <code className="text-muted-foreground text-xs">{l.word}</code>
                  </label>
                  {on ? (
                    <div className="flex flex-wrap items-center gap-3 ps-6">
                      <label htmlFor={id} className="text-sm">
                        Strength
                      </label>
                      <input
                        id={id}
                        type="range"
                        min={LOOK_MIN}
                        max={LOOK_MAX}
                        step={0.1}
                        value={on.weight}
                        onChange={(e) => strength(l.name, Number(e.target.value))}
                        aria-label={`Strength of ${l.title}`}
                      />
                      <span className="text-muted-foreground text-sm tabular-nums">
                        {on.weight.toFixed(1)}
                      </span>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
