"use client";

import {
  type AudioSource,
  type DubFit,
  type DubLine,
  type DubScript,
  type ParsedEvent,
  type SavedVoice,
  type SpeakerBasis,
  type Speech,
  type Track,
  type VoiceApi,
  type VoiceFrom,
  dubScript,
  makeDub,
} from "@wasifyai/client";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { ModelPicker } from "./ModelPicker";
import { clock, pickModel } from "./format";
import { useVoiceModels } from "./use-voice-models";

export const LANGUAGE_NAMES: Record<string, string> = {
  bg: "Bulgarian", cs: "Czech", da: "Danish", de: "German", el: "Greek", en: "English",
  es: "Spanish", et: "Estonian", fi: "Finnish", fr: "French", hr: "Croatian", hu: "Hungarian",
  it: "Italian", ja: "Japanese", ko: "Korean", lt: "Lithuanian", lv: "Latvian", mt: "Maltese",
  nl: "Dutch", pl: "Polish", pt: "Portuguese", ro: "Romanian", ru: "Russian", sk: "Slovak",
  sl: "Slovenian", sv: "Swedish", uk: "Ukrainian", zh: "Chinese",
}; // biome-ignore format: a table

export const SPEAKER_TEXT: Record<SpeakerBasis, string> = {
  own: "This is my own voice.",
  permission: "The person whose voice this is has given me permission to copy it.",
};

export type DubbingWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
  /** a recording chosen elsewhere (Your music), to start with */
  initialSource?: AudioSource | null;
  onOpenLibrary?: () => void;
};

const base = (code: string) => code.toLowerCase().split(/[-_]/)[0] ?? code;

/** The languages a model speaks, as two-letter codes; "multi" is every one the app can name. */
function spoken(languages: string[]): string[] {
  const codes = languages.map(base);
  return codes.includes("multi") ? Object.keys(LANGUAGE_NAMES) : codes;
}

type Library = { tracks: Track[]; speeches: Speech[] };

/**
 * Dubbing: a recording in another language, in two steps so the person can read and change the
 * translation before anything is spoken. The voice is the original speaker's (copied, which needs the
 * person's word that it is theirs or allowed), a voice they saved, or a built-in one.
 */
export function DubbingWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
  initialSource,
  onOpenLibrary,
}: DubbingWorkspaceProps) {
  const [library, setLibrary] = useState<Library | null>(null);
  const [source, setSource] = useState<AudioSource | null>(initialSource ?? null);
  const [language, setLanguage] = useState("");
  const [keepBackground, setKeepBackground] = useState(true);
  const [voiceFrom, setVoiceFrom] = useState<VoiceFrom>("speaker");
  const [basis, setBasis] = useState<SpeakerBasis | null>(null);
  const [saved, setSaved] = useState<SavedVoice[]>([]);
  const [savedId, setSavedId] = useState("");
  const [builtin, setBuiltin] = useState("");
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [script, setScript] = useState<DubScript | null>(null);
  const [lines, setLines] = useState<DubLine[]>([]);
  const [step, setStep] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [made, setMade] = useState<{
    track: Pick<Track, "id" | "title" | "seconds" | "audio_url">;
    fit: DubFit;
  } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const working = step !== null;

  const task = voiceFrom === "builtin" ? "speak" : "clone"; // copying a voice, saved or not, is "clone"
  const voices = useVoiceModels(api, task);
  const speakers = useVoiceModels(api, "speak");
  const clones = useVoiceModels(api, "clone");

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    Promise.all([api.tracks({ limit: 200 }), api.speeches(200)])
      .then(([tracks, speeches]) => setLibrary({ tracks, speeches }))
      .catch(() => setLibrary({ tracks: [], speeches: [] }));
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

  // the languages a voice can be made in: what some speaking or copying model knows
  const languages = [
    ...new Set([...speakers.models, ...clones.models].flatMap((m) => spoken(m.languages))),
  ]
    .filter((c) => LANGUAGE_NAMES[c])
    .sort((a, b) => (LANGUAGE_NAMES[a] ?? a).localeCompare(LANGUAGE_NAMES[b] ?? b));
  const usable = voices.models.filter((m) => !language || spoken(m.languages).includes(language));
  const chosen = usable.find((m) => m.id === modelId) ?? pickModel(usable, task, modelId);
  const ready = chosen?.state === "ready";
  const savedUsable = saved.filter((v) => v.kind === "clone");

  const picked = (() => {
    if (!source || !library) return null;
    if (source.kind === "track") {
      const t = library.tracks.find((x) => x.id === source.id);
      return t ? { title: t.title, seconds: t.seconds, url: t.audio_url } : null;
    }
    const s = library.speeches.find((x) => x.id === source.id);
    return s ? { title: s.text.slice(0, 60), seconds: s.seconds, url: s.audio_url } : null;
  })();

  const voiceOk =
    voiceFrom === "speaker"
      ? basis !== null && (script?.vocalsTrack !== undefined || false)
      : voiceFrom === "saved"
        ? savedId !== ""
        : true;
  const readyToWrite = source !== null && language !== "" && !working;
  const readyToMake =
    script !== null && lines.every((l) => l.text.trim()) && voiceOk && ready && !working;

  async function write() {
    if (!source || !language) return;
    setProblem(null);
    setMade(null);
    setScript(null);
    setStep("Starting");
    abort.current = new AbortController();
    const signal = abort.current.signal;
    try {
      // copying the speaker's voice needs the voice on its own, so the background is separated then
      const r = await dubScript(
        runs,
        { source, language, background: keepBackground || voiceFrom === "speaker" },
        signal,
        setStep,
      );
      if (r.ok) {
        setScript(r.script);
        setLines(r.script.segments);
      } else setProblem(r.message);
    } catch (e) {
      if (!signal.aborted)
        setProblem(e instanceof Error ? e.message : "That could not be written.");
    } finally {
      setStep(null);
    }
  }

  async function make() {
    if (!source || !script || !readyToMake || !chosen) return;
    setProblem(null);
    setMade(null);
    setStep("Starting");
    abort.current = new AbortController();
    const signal = abort.current.signal;
    try {
      const r = await makeDub(
        runs,
        {
          source,
          language,
          segments: lines,
          voiceFrom,
          model: chosen.id,
          ...(voiceFrom === "speaker" && basis ? { speakerBasis: basis } : {}),
          ...(voiceFrom === "saved" ? { savedVoice: savedId } : {}),
          ...(voiceFrom === "builtin" && builtin ? { voice: builtin } : {}),
          ...(script.vocalsTrack ? { vocalsTrack: script.vocalsTrack } : {}),
          ...(keepBackground && script.backgroundTrack
            ? { backgroundTrack: script.backgroundTrack }
            : {}),
        },
        signal,
        setStep,
      );
      if (r.ok) setMade({ track: r.track, fit: r.fit });
      else setProblem(r.message);
    } catch (e) {
      if (!signal.aborted) setProblem(e instanceof Error ? e.message : "That could not be made.");
    } finally {
      setStep(null);
      void voices.reload();
    }
  }

  if (library === null || voices.loading || speakers.loading || clones.loading) return <Spinner />;
  if (voices.error) {
    return (
      <p role="alert" className="text-destructive">
        {voices.error}
      </p>
    );
  }
  const builtinVoices = chosen?.voices ?? [];
  return (
    <div className="mx-auto grid w-full min-w-0 max-w-3xl gap-6">
      <p className="text-muted-foreground">
        Speak a recording again in another language. You read and change the translation before
        anything is spoken. It all runs on this computer.
      </p>

      <fieldset className="grid gap-3" disabled={working}>
        <legend className="font-medium">1. The recording and the language</legend>
        <div className="grid gap-2">
          <Label htmlFor="dub-source">Which recording?</Label>
          <select
            id="dub-source"
            className="h-10 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            value={source ? `${source.kind}:${source.id}` : ""}
            onChange={(e) => {
              const [kind, ...id] = e.target.value.split(":");
              setSource(kind === "track" || kind === "speech" ? { kind, id: id.join(":") } : null);
              setScript(null);
              setMade(null);
            }}
          >
            <option value="">Choose…</option>
            {library.tracks.length > 0 ? (
              <optgroup label="Your music and recordings">
                {library.tracks.map((t) => (
                  <option key={t.id} value={`track:${t.id}`}>
                    {t.title} ({clock(t.seconds)})
                  </option>
                ))}
              </optgroup>
            ) : null}
            {library.speeches.length > 0 ? (
              <optgroup label="Speech you made">
                {library.speeches.map((s) => (
                  <option key={s.id} value={`speech:${s.id}`}>
                    {s.text.slice(0, 50)} ({clock(s.seconds)})
                  </option>
                ))}
              </optgroup>
            ) : null}
          </select>
          {picked ? (
            // biome-ignore lint/a11y/useMediaCaption: the recording the person chose
            <audio controls preload="none" src={picked.url} className="h-10 w-full" />
          ) : library.tracks.length + library.speeches.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Nothing in the library yet.{" "}
              {onOpenLibrary ? (
                <button
                  type="button"
                  className="underline underline-offset-4"
                  onClick={onOpenLibrary}
                >
                  Open Your music
                </button>
              ) : null}{" "}
              to add a recording.
            </p>
          ) : null}
        </div>
        <div className="grid gap-2">
          <Label htmlFor="dub-language">Dub it into</Label>
          <select
            id="dub-language"
            className="h-10 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            value={language}
            onChange={(e) => {
              setLanguage(e.target.value);
              setScript(null);
              setMade(null);
            }}
          >
            <option value="">Choose a language…</option>
            {languages.map((c) => (
              <option key={c} value={c}>
                {LANGUAGE_NAMES[c]}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={keepBackground}
            onChange={(e) => setKeepBackground(e.target.checked)}
          />
          Keep the music and sounds behind the voice
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={!readyToWrite} onClick={() => void write()}>
            {working && !script ? "Writing the script…" : "Write the script"}
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
          ) : null}
        </div>
      </fieldset>

      {script ? (
        <fieldset className="grid gap-3" disabled={working}>
          <legend className="font-medium">2. The script: read it, change what you like</legend>
          <ol className="grid gap-3">
            {lines.map((l, i) => (
              <li key={`${l.start}-${l.end}`} className="grid gap-1 rounded-lg border p-3">
                <div className="flex items-baseline gap-2 text-muted-foreground text-xs">
                  <time className="tabular-nums">
                    {clock(l.start)}–{clock(l.end)}
                  </time>
                  <span className="min-w-0 flex-1">{l.source}</span>
                </div>
                <Textarea
                  aria-label={`Line ${i + 1}`}
                  rows={2}
                  value={l.text}
                  onChange={(e) =>
                    setLines((all) =>
                      all.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)),
                    )
                  }
                />
              </li>
            ))}
          </ol>
        </fieldset>
      ) : null}

      {script ? (
        <fieldset className="grid gap-3" disabled={working}>
          <legend className="font-medium">3. The voice</legend>
          <div role="radiogroup" aria-label="Whose voice" className="grid gap-2">
            <label className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="dub-voice"
                checked={voiceFrom === "speaker"}
                onChange={() => setVoiceFrom("speaker")}
                className="mt-1"
              />
              The original speaker's voice, copied from the recording
            </label>
            {voiceFrom === "speaker" ? (
              <div role="radiogroup" aria-label="Whose voice it is" className="ms-6 grid gap-1.5">
                {(Object.keys(SPEAKER_TEXT) as SpeakerBasis[]).map((b) => (
                  <label key={b} className="flex items-start gap-2 text-sm">
                    <input
                      type="radio"
                      name="dub-basis"
                      checked={basis === b}
                      onChange={() => setBasis(b)}
                      className="mt-1"
                    />
                    {SPEAKER_TEXT[b]}
                  </label>
                ))}
                {!script.vocalsTrack ? (
                  <p className="text-destructive text-sm">
                    Write the script again: the voice has to be separated to be copied.
                  </p>
                ) : null}
              </div>
            ) : null}
            <label className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="dub-voice"
                checked={voiceFrom === "saved"}
                onChange={() => setVoiceFrom("saved")}
                className="mt-1"
              />
              A voice I saved
            </label>
            {voiceFrom === "saved" ? (
              <select
                aria-label="Saved voice"
                className="ms-6 h-10 rounded-md border border-input bg-transparent px-3 text-sm"
                value={savedId}
                onChange={(e) => setSavedId(e.target.value)}
              >
                <option value="">
                  {savedUsable.length ? "Choose a voice…" : "No saved voices yet"}
                </option>
                {savedUsable.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            ) : null}
            <label className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="dub-voice"
                checked={voiceFrom === "builtin"}
                onChange={() => setVoiceFrom("builtin")}
                className="mt-1"
              />
              A built-in voice (not every language has one)
            </label>
            {voiceFrom === "builtin" && builtinVoices.length > 0 ? (
              <select
                aria-label="Built-in voice"
                className="ms-6 h-10 rounded-md border border-input bg-transparent px-3 text-sm"
                value={builtin}
                onChange={(e) => setBuiltin(e.target.value)}
              >
                <option value="">The model's usual voice</option>
                {builtinVoices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          {usable.length === 0 ? (
            <p role="alert" className="text-destructive text-sm">
              No voice model speaks {LANGUAGE_NAMES[language] ?? language} this way. Get one in
              Models or choose another voice.
            </p>
          ) : (
            <ModelPicker
              models={usable}
              task={task}
              value={chosen?.id ?? null}
              onChange={(id) => {
                setModelId(id);
                onModelChosen?.(id);
              }}
              onGetModel={onGetModel}
              disabled={working}
            />
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={!readyToMake} onClick={() => void make()}>
              {working ? "Making the dub…" : "Make the dub"}
            </Button>
            {voiceFrom === "speaker" && basis === null ? (
              <span className="text-muted-foreground text-sm">
                Say whose voice it is to copy it.
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
        <section aria-label="The dub" className="grid gap-2 rounded-xl border bg-card p-3">
          <div className="flex items-baseline gap-2">
            <span className="font-medium">{made.track.title}</span>
            <span className="text-muted-foreground text-xs">{clock(made.track.seconds)}</span>
            {onOpenLibrary ? (
              <button
                type="button"
                className="ms-auto text-sm underline underline-offset-4"
                onClick={onOpenLibrary}
              >
                Open Your music
              </button>
            ) : null}
          </div>
          {/* biome-ignore lint/a11y/useMediaCaption: the dub the person asked for */}
          <audio controls src={made.track.audio_url} className="h-10 w-full" />
          <p className="text-muted-foreground text-xs">
            {made.fit.lines} lines
            {made.fit.sped_up > 0
              ? `, ${made.fit.sped_up} played a little faster to fit their time`
              : ""}
            {made.fit.max_overflow_s > 0.3
              ? `. One line runs ${made.fit.max_overflow_s.toFixed(1)} seconds past its place: shorten it in the script and make the dub again.`
              : "."}
          </p>
        </section>
      ) : null}
    </div>
  );
}
