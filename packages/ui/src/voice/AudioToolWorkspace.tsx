"use client";

import {
  type AudioSource,
  type ParsedEvent,
  type SavedVoice,
  type Speech,
  type ToolTrack,
  type Track,
  type VoiceApi,
  convertVoice,
  editWords,
  separateAudio,
} from "@wasifyai/client";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { ModelPicker } from "./ModelPicker";
import { RuntimeCard } from "./RuntimeCard";
import { clock, pickModel } from "./format";
import { useVoiceModels } from "./use-voice-models";

export type AudioTool = "separate" | "convert" | "edit";

export type AudioToolWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  tool: AudioTool;
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
  /** a recording chosen elsewhere (Your music), to start with */
  initialSource?: AudioSource | null;
  /** open Your music, or the Voices screen when a voice is needed */
  onOpenLibrary?: () => void;
  onOpenVoices?: () => void;
};

const TEXT: Record<AudioTool, { ask: string; blurb: string; button: string; busy: string }> = {
  separate: {
    ask: "Which recording?",
    blurb:
      "Split a song into its parts: the singing, the drums, the bass and the rest. Every part is kept in Your music.",
    button: "Split it",
    busy: "Splitting",
  },
  convert: {
    ask: "Which recording?",
    blurb:
      "Make a recording sound like another voice. The voice has to be one you saved from a recording, with your say-so that it is yours or that you have permission.",
    button: "Change the voice",
    busy: "Changing the voice",
  },
  edit: {
    ask: "Which speech?",
    blurb:
      "Change some words in a recording of speech. The voice and the rest of what is said stay as they were.",
    button: "Change the words",
    busy: "Changing the words",
  },
};

type Library = { tracks: Track[]; speeches: Speech[] };

/**
 * One screen for the three audio tools, with the model chosen from the list (ADR-0066): pick a recording
 * from the library (or add one from this computer), set what the tool needs, and the result is kept in
 * Your music next to what it came from.
 */
export function AudioToolWorkspace({
  api,
  runs,
  tool,
  onGetModel,
  initialModel,
  onModelChosen,
  initialSource,
  onOpenLibrary,
  onOpenVoices,
}: AudioToolWorkspaceProps) {
  const { models, runtime, error, loading, reload } = useVoiceModels(api, tool);
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [library, setLibrary] = useState<Library | null>(null);
  const [source, setSource] = useState<AudioSource | null>(initialSource ?? null);
  const [voices, setVoices] = useState<SavedVoice[]>([]);
  const [voice, setVoice] = useState("");
  const [kept, setKept] = useState<string[] | null>(null); // separate: the parts to keep
  const [before, setBefore] = useState("");
  const [after, setAfter] = useState("");
  const [writing, setWriting] = useState(false);
  const [step, setStep] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [made, setMade] = useState<ToolTrack[]>([]);
  const abort = useRef<AbortController | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, tool, modelId);
  const working = step !== null;
  const ready = chosen?.state === "ready";
  const text = TEXT[tool];
  const stems = chosen?.separate?.stems ?? [];
  const wanted = kept ?? stems;

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    Promise.all([api.tracks({ limit: 200 }), api.speeches(200)])
      .then(([tracks, speeches]) => setLibrary({ tracks, speeches }))
      .catch(() => setLibrary({ tracks: [], speeches: [] }));
  }, [api]);
  useEffect(() => {
    if (tool !== "convert") return;
    api
      .voices("clone")
      .then(setVoices)
      .catch(() => undefined);
  }, [api, tool]);
  useEffect(() => {
    if (!working) return;
    setWaited(0);
    const id = setInterval(() => setWaited((w) => w + 1), 1000);
    return () => clearInterval(id);
  }, [working]);
  // a new model has its own parts
  // biome-ignore lint/correctness/useExhaustiveDependencies: the parts follow the model
  useEffect(() => setKept(null), [chosen?.id]);

  const picked: { title: string; seconds: number; url: string } | null = (() => {
    if (!source || !library) return null;
    if (source.kind === "track") {
      const t = library.tracks.find((x) => x.id === source.id);
      return t ? { title: t.title, seconds: t.seconds, url: t.audio_url } : null;
    }
    const s = library.speeches.find((x) => x.id === source.id);
    return s ? { title: s.text.slice(0, 60), seconds: s.seconds, url: s.audio_url } : null;
  })();
  const limit =
    chosen?.separate?.max_source_s ??
    chosen?.convert?.max_source_s ??
    chosen?.speech_edit?.max_source_s;
  const tooLong = picked && limit ? picked.seconds > limit : false;

  async function addFile(file: File) {
    setProblem(null);
    try {
      const t = await api.importTrack(file);
      setLibrary((l) => ({ tracks: [t, ...(l?.tracks ?? [])], speeches: l?.speeches ?? [] }));
      setSource({ kind: "track", id: t.id });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That recording could not be added.");
    }
  }

  async function writeDown() {
    if (!source || writing) return;
    setWriting(true);
    setProblem(null);
    try {
      const w = await api.words(source);
      setBefore(w.text);
      setAfter(w.text);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The words could not be written down.");
    } finally {
      setWriting(false);
    }
  }

  async function run() {
    if (!chosen || !source || working) return;
    setProblem(null);
    setMade([]);
    setStep("Starting");
    abort.current = new AbortController();
    const signal = abort.current.signal;
    try {
      const r =
        tool === "separate"
          ? await separateAudio(
              runs,
              {
                source,
                model: chosen.id,
                stems: wanted.length < stems.length ? wanted : undefined,
              },
              signal,
              setStep,
            )
          : tool === "convert"
            ? await convertVoice(runs, { source, voice, model: chosen.id }, signal, setStep)
            : await editWords(
                runs,
                { source, oldText: before, newText: after, model: chosen.id },
                signal,
                setStep,
              );
      if (r.ok) setMade(r.tracks);
      else setProblem(r.message);
    } catch (e) {
      if (!signal.aborted) setProblem(e instanceof Error ? e.message : "That could not be done.");
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
  if (loading || library === null) return <Spinner />;

  const missing =
    tool === "convert"
      ? !voice
      : tool === "edit"
        ? before.trim().length < 2 || after.trim().length < 2 || before.trim() === after.trim()
        : wanted.length === 0;
  const speed = chosen?.measured.speed_x;
  return (
    <div className="mx-auto grid w-full min-w-0 max-w-3xl gap-6">
      <p className="text-muted-foreground">{text.blurb}</p>
      {runtime && chosen?.engine !== "comfyui" ? (
        <RuntimeCard runtime={runtime} api={api} onChanged={reload} />
      ) : null}
      <ModelPicker
        models={models}
        task={tool}
        value={chosen?.id ?? null}
        onChange={(id) => {
          setModelId(id);
          onModelChosen?.(id);
        }}
        onGetModel={onGetModel}
        disabled={working}
      />
      <div className="grid gap-2">
        <Label htmlFor={`source-${tool}`}>{text.ask}</Label>
        <div className="flex flex-wrap items-center gap-2">
          <select
            id={`source-${tool}`}
            className="h-10 min-w-0 flex-1 rounded-md border border-input bg-transparent px-3 text-sm"
            value={source ? `${source.kind}:${source.id}` : ""}
            disabled={working}
            onChange={(e) => {
              const [kind, ...id] = e.target.value.split(":");
              setSource(kind === "track" || kind === "speech" ? { kind, id: id.join(":") } : null);
              setBefore("");
              setAfter("");
              setMade([]);
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
          <input
            ref={picker}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.caf,.aiff"
            className="sr-only"
            aria-label="Add a recording from this computer"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void addFile(f);
            }}
          />
          <Button variant="outline" disabled={working} onClick={() => picker.current?.click()}>
            Add a recording
          </Button>
        </div>
        {picked ? (
          // biome-ignore lint/a11y/useMediaCaption: the recording the person chose
          <audio controls preload="none" src={picked.url} className="h-10 w-full" />
        ) : null}
        {tooLong && limit ? (
          <p role="alert" className="text-destructive text-sm">
            {chosen?.title} takes a recording of up to {clock(limit)}. This one is{" "}
            {clock(picked?.seconds ?? 0)}.
          </p>
        ) : null}
        {library.tracks.length + library.speeches.length === 0 && onOpenLibrary ? (
          <p className="text-muted-foreground text-sm">
            Nothing in the library yet. Add a recording, or make something first.
          </p>
        ) : null}
      </div>

      {tool === "separate" && stems.length > 0 ? (
        <fieldset className="grid gap-2" disabled={working}>
          <legend className="font-medium text-sm">Keep these parts</legend>
          <div className="flex flex-wrap gap-4">
            {stems.map((name) => (
              <label key={name} className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={wanted.includes(name)}
                  onChange={(e) =>
                    setKept(e.target.checked ? [...wanted, name] : wanted.filter((x) => x !== name))
                  }
                />
                {name}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}

      {tool === "convert" ? (
        <div className="grid gap-2">
          <Label htmlFor="convert-voice">Sound like</Label>
          <select
            id="convert-voice"
            className="h-10 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            value={voice}
            disabled={working || voices.length === 0}
            onChange={(e) => setVoice(e.target.value)}
          >
            <option value="">{voices.length ? "Choose a voice…" : "No saved voices yet"}</option>
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.consent.basis === "own" ? "your own voice" : "used with permission"})
              </option>
            ))}
          </select>
          {voices.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Save a voice from a recording first.{" "}
              {onOpenVoices ? (
                <button
                  type="button"
                  className="underline underline-offset-4"
                  onClick={onOpenVoices}
                >
                  Open Voices
                </button>
              ) : null}
            </p>
          ) : (
            <p className="text-muted-foreground text-sm">
              Only change a voice into your own, or into one you have permission to use.
            </p>
          )}
        </div>
      ) : null}

      {tool === "edit" ? (
        <div className="grid gap-3">
          <div className="flex items-center gap-2">
            <Label htmlFor="edit-before">What it says now</Label>
            <Button
              size="xs"
              variant="outline"
              className="ms-auto"
              disabled={!source || working || writing}
              onClick={() => void writeDown()}
            >
              {writing ? "Writing it down…" : "Write down what it says"}
            </Button>
          </div>
          <Textarea
            id="edit-before"
            rows={3}
            value={before}
            disabled={working}
            onChange={(e) => {
              if (after === before) setAfter(e.target.value);
              setBefore(e.target.value);
            }}
          />
          <Label htmlFor="edit-after">What it should say</Label>
          <Textarea
            id="edit-after"
            rows={3}
            value={after}
            disabled={working}
            placeholder="Change a few words in the text above"
            onChange={(e) => setAfter(e.target.value)}
          />
          <p className="text-muted-foreground text-sm">
            Change a few words at a time: up to {chosen?.speech_edit?.max_changes ?? 5} separate
            changes. English and Chinese work best.
          </p>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={() => void run()}
          disabled={!ready || !source || working || missing || tooLong}
        >
          {working ? `${text.busy}…` : text.button}
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
        ) : speed && picked ? (
          <span className="text-muted-foreground text-sm">
            About {Math.max(1, Math.round(picked.seconds / speed))} seconds of work on this
            computer, plus a few to load the model.
          </span>
        ) : null}
        {!ready && chosen ? (
          <span className="text-muted-foreground text-sm">
            Set this model up first (see above).
          </span>
        ) : null}
      </div>
      {problem ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}
      {made.length > 0 ? (
        <section aria-label="Result" className="grid gap-3">
          <div className="flex items-center gap-3">
            <h2 className="me-auto font-semibold">
              {made.length > 1 ? "Kept in Your music" : "Kept in Your music"}
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
            {made.map((t) => (
              <li key={t.id} className="grid gap-2 rounded-xl border bg-card p-3">
                <span className="font-medium">
                  {t.stem ?? t.title}{" "}
                  <span className="text-muted-foreground text-xs">{clock(t.seconds)}</span>
                </span>
                {/* biome-ignore lint/a11y/useMediaCaption: the result of the tool */}
                <audio controls preload="none" src={t.audio_url} className="h-10 w-full" />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
