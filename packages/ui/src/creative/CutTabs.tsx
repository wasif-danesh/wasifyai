"use client";
// The Voice and Titles tabs of the Make panel in the Cut step (the amendment to ADR-0090). Voice is the song's
// words as captions: on or off, each line's words, and the words where they were sung again. Titles are a title
// or a lower third over the cut, drawn with the captions. Motion graphics' templates over the cut come later.
import type { CaptionKind, CutEdit, CutState } from "@wasifyai/client";
import { useId, useState } from "react";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { Input } from "../components/input";
import { Segmented } from "../components/segmented";
import { actions, field, hint } from "../styles";
import { clock } from "./CutStage";

export function CaptionsTab({
  cut,
  timed,
  busy,
  edit,
}: {
  cut: CutState;
  /** whether the times of the song's words are known */
  timed: boolean;
  busy: boolean;
  edit: (edits: CutEdit[]) => void;
}) {
  const lines = cut.captions.filter((c) => c.kind === "line");
  return (
    <div className="grid gap-3">
      <p className="m-0 font-medium text-sm">Captions from the singing</p>
      <Checkbox
        checked={cut.captions_on}
        disabled={busy || !lines.length}
        onCheckedChange={(on) => edit([{ op: "captions", on }])}
        label="Show the song's words"
        hint="Each line shows while it is sung."
      />
      {timed ? (
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => edit([{ op: "song_lines" }])}
        >
          Take the words from the song again
        </Button>
      ) : (
        <p className={`${hint} m-0`}>
          The times of this song's words are not known, so there are no captions from the singing.
          Titles still work.
        </p>
      )}
      <ol className="m-0 grid list-none gap-1.5 p-0">
        {lines.map((c) => (
          <li key={`${c.id}:${c.text}`} className="grid gap-0.5">
            <span className={hint}>
              {clock(c.start)} to {clock(c.end)}
            </span>
            <LineWords
              text={c.text}
              label={`Words at ${clock(c.start)}`}
              disabled={busy}
              onSave={(text) => edit([{ op: "caption", caption_id: c.id, text }])}
            />
          </li>
        ))}
      </ol>
    </div>
  );
}

function LineWords({
  text,
  label,
  disabled,
  onSave,
}: {
  text: string;
  label: string;
  disabled: boolean;
  onSave: (text: string) => void;
}) {
  const [now, setNow] = useState(text);
  const save = () => {
    const words = now.trim();
    if (words && words !== text) onSave(words);
  };
  return (
    <Input
      aria-label={label}
      value={now}
      maxLength={160}
      disabled={disabled}
      onChange={(e) => setNow(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === "Enter") save();
      }}
    />
  );
}

const KINDS = [
  { value: "title", label: "Title" },
  { value: "lower", label: "Lower third" },
];

export function TitlesTab({
  cut,
  busy,
  edit,
  at,
}: {
  cut: CutState;
  busy: boolean;
  edit: (edits: CutEdit[]) => void;
  /** where the video is playing now, to start a title there */
  at: () => number;
}) {
  const id = useId();
  const [kind, setKind] = useState<CaptionKind>("title");
  const [text, setText] = useState("");
  const [length, setLength] = useState("3");
  const song = cut.summary.song_s;
  const titles = cut.captions.filter((c) => c.kind !== "line");
  const add = () => {
    const words = text.trim();
    const start = Math.min(Math.max(0, at()), Math.max(0, song - 0.5));
    const end = Math.min(song, start + Math.max(0.5, Number(length) || 3));
    if (!words) return;
    edit([
      {
        op: "add_caption",
        kind,
        text: words,
        start: Number(start.toFixed(2)),
        end: Number(end.toFixed(2)),
      },
    ]);
    setText("");
  };
  return (
    <div className="grid gap-3">
      <p className="m-0 font-medium text-sm">A title or a lower third over the cut</p>
      <Segmented
        label="Kind"
        value={kind}
        onValueChange={(v) => setKind(v as CaptionKind)}
        options={KINDS}
      />
      <div className={field}>
        <label htmlFor={`${id}-words`} className="font-medium text-sm">
          Words
        </label>
        <Input
          id={`${id}-words`}
          value={text}
          maxLength={160}
          placeholder={kind === "title" ? "Dawn drive" : "Mira, on the road home"}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <div className={field}>
        <label htmlFor={`${id}-length`} className="font-medium text-sm">
          Seconds on screen
        </label>
        <Input
          id={`${id}-length`}
          type="number"
          min={0.5}
          max={30}
          step={0.5}
          value={length}
          onChange={(e) => setLength(e.target.value)}
        />
      </div>
      <div className={actions}>
        <Button type="button" disabled={busy || !text.trim()} onClick={add}>
          Add
        </Button>
      </div>
      <p className={`${hint} m-0`}>
        It starts where the video is playing; move it on the timeline by a beat. Motion graphics
        templates over the cut come in a later stage.
      </p>
      {titles.length ? (
        <ul className="m-0 grid list-none gap-1 p-0 text-sm">
          {titles.map((c) => (
            <li key={c.id} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate">
                {c.text} <span className={hint}>{clock(c.start)}</span>
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => edit([{ op: "remove_caption", caption_id: c.id }])}
              >
                Take out
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
