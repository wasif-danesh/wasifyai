"use client";

import {
  type BookChapter,
  type ParsedEvent,
  type SavedVoice,
  type ToolTrack,
  type VoiceApi,
  makeAudiobook,
} from "@wasifyai/client";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { ModelPicker } from "./ModelPicker";
import { OptionFields } from "./OptionFields";
import { clock, pickModel } from "./format";
import { useVoiceModels } from "./use-voice-models";

export const TEXT_ACCEPT = ".txt,.md,.markdown,text/plain,text/markdown";
const WHOLE_MAX_CHARS = 100_000;
const SPOKEN_CHARS_PER_SECOND = 13;

export type AudiobookWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
  onOpenLibrary?: () => void;
};

type Made = { tracks: (ToolTrack & { chapter: number })[]; book: ToolTrack | null };

/**
 * An audiobook: a long text becomes chapters the person can read and change, each chapter is spoken in
 * the voice they chose and kept in Your music as soon as it is done, and the whole book can be one
 * track too. A failure or a cancel leaves the chapters already made where they are.
 */
export function AudiobookWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
  onOpenLibrary,
}: AudiobookWorkspaceProps) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [chapters, setChapters] = useState<BookChapter[]>([]);
  const [planned, setPlanned] = useState(false);
  const [voiceFrom, setVoiceFrom] = useState<"builtin" | "saved">("builtin");
  const [saved, setSaved] = useState<SavedVoice[]>([]);
  const [savedId, setSavedId] = useState("");
  const [voice, setVoice] = useState("");
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [readTitles, setReadTitles] = useState(true);
  const [whole, setWhole] = useState(false);
  const [step, setStep] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [made, setMade] = useState<Made | null>(null);
  const abort = useRef<AbortController | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const working = step !== null;

  const savedVoice = saved.find((v) => v.id === savedId) ?? null;
  const task = voiceFrom === "builtin" ? "speak" : (savedVoice?.kind ?? "clone");
  const { models, error, loading, reload } = useVoiceModels(api, task);
  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, task, modelId);
  const ready = chosen?.state === "ready";
  const chars = chapters.reduce((n, c) => n + c.text.length, 0);
  const wholeOk = chars <= WHOLE_MAX_CHARS;

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    api
      .voices()
      .then(setSaved)
      .catch(() => undefined);
  }, [api]);
  useEffect(() => {
    if (!working) return;
    setWaited(0);
    const id = setInterval(() => setWaited((w) => w + 1), 1000);
    return () => clearInterval(id);
  }, [working]);

  async function plan() {
    setProblem(null);
    setMade(null);
    try {
      const p = await api.planBook(text);
      setChapters(p.chapters);
      setPlanned(true);
    } catch (e) {
      setPlanned(false);
      setProblem(e instanceof Error ? e.message : "The chapters could not be found.");
    }
  }

  async function open(f: File) {
    const words = await f.text();
    setText(words);
    if (!title.trim()) setTitle(f.name.replace(/\.[^.]+$/, ""));
    setPlanned(false);
    setChapters([]);
  }

  const edit = (i: number, change: Partial<BookChapter>) =>
    setChapters((all) =>
      all.map((c, j) => {
        if (j !== i) return c;
        const next = { ...c, ...change };
        return {
          ...next,
          chars: next.text.length,
          estimated_seconds: Math.round(next.text.length / SPOKEN_CHARS_PER_SECOND),
        };
      }),
    );

  function joinWithNext(i: number) {
    setChapters((all) => {
      const a = all[i];
      const b = all[i + 1];
      if (!a || !b) return all;
      const text = `${a.text}\n\n${b.title}.\n\n${b.text}`;
      const merged = {
        ...a,
        text,
        chars: text.length,
        estimated_seconds: Math.round(text.length / SPOKEN_CHARS_PER_SECOND),
      };
      return [...all.slice(0, i), merged, ...all.slice(i + 2)];
    });
  }

  const voiceOk = voiceFrom === "builtin" || savedId !== "";
  const canMake =
    planned &&
    chapters.length > 0 &&
    chapters.every((c) => c.text.trim()) &&
    title.trim().length > 0 &&
    ready &&
    voiceOk &&
    (!whole || wholeOk) &&
    !working;

  async function make() {
    if (!chosen || !canMake) return;
    setProblem(null);
    setMade(null);
    setStep("Starting");
    abort.current = new AbortController();
    const signal = abort.current.signal;
    const options = Object.fromEntries(
      Object.entries(values).filter(
        ([k, v]) => v !== undefined && v !== "" && chosen.options.some((o) => o.name === k),
      ),
    );
    try {
      const r = await makeAudiobook(
        runs,
        {
          title,
          chapters: chapters.map((c) => ({ title: c.title, text: c.text })),
          model: chosen.id,
          options,
          whole,
          readTitles,
          ...(voiceFrom === "builtin" ? (voice ? { voice } : {}) : { savedVoice: savedId }),
        },
        signal,
        setStep,
      );
      if (r.ok) setMade({ tracks: r.tracks, book: r.book });
      else setProblem(r.message);
    } catch (e) {
      if (!signal.aborted) setProblem(e instanceof Error ? e.message : "That could not be made.");
    } finally {
      setStep(null);
      void reload();
    }
  }

  if (error) {
    return (
      <p role="alert" className="text-destructive">
        {error}
      </p>
    );
  }
  if (loading && models.length === 0) return <Spinner />;
  const speed = chosen?.measured.speed_x;
  const spokenSeconds = chars / SPOKEN_CHARS_PER_SECOND;
  return (
    <div className="mx-auto grid w-full min-w-0 max-w-3xl gap-6">
      <p className="text-muted-foreground">
        Turn a long text into spoken chapters. You read the chapters before anything is spoken, and
        each one is kept in Your music as soon as it is done.
      </p>

      <fieldset className="grid gap-3" disabled={working}>
        <legend className="font-medium">1. The text</legend>
        <div className="grid gap-2">
          <Label htmlFor="book-title">Title of the book</Label>
          <input
            id="book-title"
            className="h-10 rounded-md border border-input bg-transparent px-3 text-sm"
            value={title}
            maxLength={120}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <div className="flex items-center gap-2">
            <Label htmlFor="book-text">The text</Label>
            <input
              ref={file}
              type="file"
              accept={TEXT_ACCEPT}
              className="sr-only"
              aria-label="Open a text file"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void open(f);
              }}
            />
            <Button
              size="xs"
              variant="outline"
              className="ms-auto"
              onClick={() => file.current?.click()}
            >
              Open a text file
            </Button>
          </div>
          <Textarea
            id="book-text"
            rows={8}
            value={text}
            placeholder={
              "Paste the text here. Chapters start at lines like “Chapter 1” or “# Title”."
            }
            onChange={(e) => {
              setText(e.target.value);
              setPlanned(false);
            }}
          />
        </div>
        <div>
          <Button disabled={text.trim().length === 0} onClick={() => void plan()}>
            Find the chapters
          </Button>
        </div>
      </fieldset>

      {planned ? (
        <fieldset className="grid gap-3" disabled={working}>
          <legend className="font-medium">
            2. The chapters ({chapters.length}, about {clock(spokenSeconds)} of speech)
          </legend>
          <ol className="grid gap-2">
            {chapters.map((c, i) => (
              <li key={`${i}-${c.chars}`} className="grid gap-2 rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <input
                    aria-label={`Title of chapter ${i + 1}`}
                    className="h-9 min-w-0 flex-1 rounded-md border border-input bg-transparent px-3 text-sm"
                    value={c.title}
                    maxLength={120}
                    onChange={(e) => edit(i, { title: e.target.value })}
                  />
                  <span className="text-muted-foreground text-xs">
                    {clock(c.estimated_seconds)}
                  </span>
                  {i + 1 < chapters.length ? (
                    <Button size="xs" variant="ghost" onClick={() => joinWithNext(i)}>
                      Join with next
                    </Button>
                  ) : null}
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => setChapters((all) => all.filter((_, j) => j !== i))}
                  >
                    Remove
                  </Button>
                </div>
                <details>
                  <summary className="cursor-pointer text-muted-foreground text-sm">
                    {c.text.slice(0, 120)}
                    {c.text.length > 120 ? "…" : ""}
                  </summary>
                  <Textarea
                    aria-label={`Words of chapter ${i + 1}`}
                    className="mt-2"
                    rows={6}
                    value={c.text}
                    onChange={(e) => edit(i, { text: e.target.value })}
                  />
                </details>
              </li>
            ))}
          </ol>
        </fieldset>
      ) : null}

      {planned ? (
        <fieldset className="grid gap-3" disabled={working}>
          <legend className="font-medium">3. The voice</legend>
          <div role="radiogroup" aria-label="Which voice" className="grid gap-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="book-voice"
                checked={voiceFrom === "builtin"}
                onChange={() => setVoiceFrom("builtin")}
              />
              A built-in voice
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="book-voice"
                checked={voiceFrom === "saved"}
                onChange={() => setVoiceFrom("saved")}
              />
              A voice I saved
            </label>
          </div>
          {voiceFrom === "saved" ? (
            <select
              aria-label="Saved voice"
              className="h-10 rounded-md border border-input bg-transparent px-3 text-sm"
              value={savedId}
              onChange={(e) => {
                setSavedId(e.target.value);
                setModelId(null);
              }}
            >
              <option value="">{saved.length ? "Choose a voice…" : "No saved voices yet"}</option>
              {saved.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          ) : null}
          <ModelPicker
            models={models}
            task={task}
            value={chosen?.id ?? null}
            onChange={(id) => {
              setModelId(id);
              setValues({});
              setVoice("");
              onModelChosen?.(id);
            }}
            onGetModel={onGetModel}
            disabled={working}
          />
          {voiceFrom === "builtin" && (chosen?.voices.length ?? 0) > 0 ? (
            <div className="grid gap-2">
              <Label htmlFor="book-voice">Voice</Label>
              <select
                id="book-voice"
                className="h-10 rounded-md border border-input bg-transparent px-3 text-sm"
                value={voice}
                onChange={(e) => setVoice(e.target.value)}
              >
                <option value="">The model's usual voice</option>
                {chosen?.voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {chosen ? (
            <OptionFields
              options={chosen.options}
              values={values}
              onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
              disabled={working}
            />
          ) : null}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={readTitles}
              onChange={(e) => setReadTitles(e.target.checked)}
            />
            Say each chapter's title before it
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={whole}
              disabled={!wholeOk}
              onChange={(e) => setWhole(e.target.checked)}
            />
            Also make one track of the whole book
            {!wholeOk ? " (only for books up to about two hours)" : ""}
          </label>
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={!canMake} onClick={() => void make()}>
              {working ? "Making the book…" : "Make the audiobook"}
            </Button>
            {working ? (
              <>
                <output className="flex items-center gap-2 text-muted-foreground text-sm">
                  <Spinner /> {step} · {clock(waited)}
                </output>
                <Button variant="ghost" onClick={() => abort.current?.abort()}>
                  Cancel
                </Button>
              </>
            ) : speed ? (
              <span className="text-muted-foreground text-sm">
                About {Math.max(1, Math.round(spokenSeconds / speed / 60))} minutes of work on this
                computer.
              </span>
            ) : null}
            {!ready && chosen ? (
              <span className="text-muted-foreground text-sm">Set this model up first.</span>
            ) : null}
          </div>
        </fieldset>
      ) : null}

      {problem ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}
      {made ? (
        <section aria-label="The audiobook" className="grid gap-3">
          <div className="flex items-center gap-3">
            <h2 className="me-auto font-semibold">
              {made.tracks.length} chapters kept in Your music
            </h2>
            {onOpenLibrary ? (
              <button
                type="button"
                className="text-sm underline underline-offset-4"
                onClick={onOpenLibrary}
              >
                Open Your music
              </button>
            ) : null}
          </div>
          <ul className="grid gap-3">
            {[...(made.book ? [{ ...made.book, chapter: 0 }] : []), ...made.tracks].map((t) => (
              <li key={t.id} className="grid gap-2 rounded-xl border bg-card p-3">
                <span className="font-medium">
                  {t.title}{" "}
                  <span className="text-muted-foreground text-xs">{clock(t.seconds)}</span>
                </span>
                {/* biome-ignore lint/a11y/useMediaCaption: the book the person made from their own text */}
                <audio controls preload="none" src={t.audio_url} className="h-10 w-full" />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
