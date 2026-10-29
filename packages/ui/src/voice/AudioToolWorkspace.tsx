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
import { AudioLines, FolderOpen, Scissors, Shuffle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { Label } from "../components/label";
import { MakeScreen } from "../components/make-screen";
import { Player } from "../components/player";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Select } from "../components/select";
import { Spinner } from "../components/spinner";
import { Stage, type StageState } from "../components/stage";
import { Textarea } from "../components/textarea";
import { LoadingModels, ModelPicker, NotReadyText } from "./ModelPicker";
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
  /** the screen's heading and the line under it */
  title?: string;
  lead?: string;
};

const TEXT: Record<
  AudioTool,
  {
    title: string;
    ask: string;
    blurb: string;
    button: string;
    busy: string;
    empty: string;
    mode: string;
  }
> = {
  separate: {
    title: "Split into parts",
    ask: "Which recording?",
    blurb:
      "Split a song into its parts: the singing, the drums, the bass and the rest. Every part is kept in Your music.",
    button: "Split the song",
    busy: "Splitting the song…",
    empty: "The parts appear here.",
    mode: "stem",
  },
  convert: {
    title: "Change a voice",
    ask: "Which recording?",
    blurb:
      "Make a recording sound like another voice. The voice has to be one you saved from a recording, with your say-so that it is yours or that you have permission.",
    button: "Change the voice",
    busy: "Changing the voice…",
    empty: "The new recording appears here.",
    mode: "converted",
  },
  edit: {
    title: "Edit speech",
    ask: "Which speech?",
    blurb:
      "Change some words in a recording of speech. The voice and the rest of what is said stay as they were.",
    button: "Change the words",
    busy: "Changing the words…",
    empty: "The changed speech appears here.",
    mode: "edited",
  },
};

const ICON = { separate: Scissors, convert: Shuffle, edit: AudioLines } as const;

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
  title,
  lead,
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
  const [opened, setOpened] = useState<Track | null>(null); // a result from the recent strip
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
    setOpened(null);
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
      if (r.ok) {
        setMade(r.tracks);
        // the results join the library, so the recent strip has them
        void api
          .tracks({ limit: 200 })
          .then((tracks) => setLibrary((l) => ({ tracks, speeches: l?.speeches ?? [] })))
          .catch(() => undefined);
      } else setProblem(r.message);
    } catch (e) {
      if (!signal.aborted) setProblem(e instanceof Error ? e.message : "That could not be done.");
    } finally {
      setStep(null);
      void reload();
    }
  }

  if (error) {
    return (
      <p role="alert" className="p-6 text-destructive">
        {error}
      </p>
    );
  }
  if (loading || library === null) return <LoadingModels />;

  const missing =
    tool === "convert"
      ? !voice
      : tool === "edit"
        ? before.trim().length < 2 || after.trim().length < 2 || before.trim() === after.trim()
        : wanted.length === 0;
  const speed = chosen?.measured.speed_x;
  const results: ToolTrack[] = opened ? [opened] : made;
  const sourceOptions = [
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
            options: library.speeches.map((sp) => ({
              value: `speech:${sp.id}`,
              label: `${sp.text.slice(0, 50)} (${clock(sp.seconds)})`,
            })),
          },
        ]
      : []),
  ];

  const resultActions: Action[] = onOpenLibrary
    ? [
        {
          label: "Open Your music",
          onSelect: onOpenLibrary,
          icon: <FolderOpen aria-hidden="true" />,
        },
      ]
    : [];
  const stage: StageState = working
    ? {
        kind: "working",
        label: text.busy,
        text: `${step} · ${clock(waited)}`,
        onStop: () => abort.current?.abort(),
      }
    : problem && results.length === 0
      ? { kind: "error", message: problem, onReset: () => setProblem(null) }
      : results.length > 0
        ? {
            kind: "result",
            children: (
              <ul className="m-0 grid w-full list-none gap-3 p-0">
                {results.map((t) => (
                  <li key={t.id} className="grid gap-1.5 text-start">
                    <span className="font-medium text-sm">{t.stem ?? t.title}</span>
                    <Player
                      src={t.audio_url}
                      title={t.stem ?? t.title}
                      duration={t.seconds}
                      waveform
                    />
                  </li>
                ))}
              </ul>
            ),
            caption: (
              <div className="grid gap-1">
                <span>
                  {results.length > 1 ? "The parts are kept" : "It is kept"} in Your music, next to
                  the recording it came from.
                </span>
                {problem ? (
                  <p role="alert" className="m-0 text-destructive text-sm">
                    {problem}
                  </p>
                ) : null}
              </div>
            ),
            actions: resultActions,
          }
        : {
            kind: "empty",
            icon: ICON[tool],
            title: text.empty,
            text: `Choose a recording on the left, then press ${text.button}.`,
          };

  const recent: RecentItem[] = library.tracks
    .filter((t) => t.mode === text.mode)
    .slice(0, 24)
    .map((t) => ({
      id: t.id,
      cover: (
        <span className="grid size-full place-items-center gap-0.5 bg-muted p-1 text-center">
          <AudioLines className="size-4 text-muted-foreground" aria-hidden="true" />
          <span className="line-clamp-2 text-xs leading-tight">{t.title}</span>
        </span>
      ),
      label: `Open: ${t.title}`,
      current: opened?.id === t.id,
      onOpen: () => {
        if (working) return;
        setProblem(null);
        setOpened(t);
      },
    }));

  return (
    <MakeScreen
      title={title ?? text.title}
      lead={lead ?? text.blurb}
      ask={
        <>
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
            <Label htmlFor={`source-${tool}`} className="font-semibold text-ui-lg">
              {text.ask}
            </Label>
            <Select
              id={`source-${tool}`}
              value={source ? `${source.kind}:${source.id}` : undefined}
              placeholder={sourceOptions.length ? "Choose…" : "Nothing in the library yet"}
              disabled={working || sourceOptions.length === 0}
              options={sourceOptions}
              onValueChange={(v) => {
                const [kind, ...id] = v.split(":");
                setSource(
                  kind === "track" || kind === "speech" ? { kind, id: id.join(":") } : null,
                );
                setBefore("");
                setAfter("");
                setMade([]);
                setOpened(null);
              }}
            />
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
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="justify-self-start"
              disabled={working}
              onClick={() => picker.current?.click()}
            >
              Add a recording
            </Button>
            {picked ? (
              <Player src={picked.url} title={picked.title} duration={picked.seconds} />
            ) : null}
            {tooLong && limit ? (
              <p role="alert" className="m-0 text-destructive text-sm">
                {chosen?.title} takes a recording of up to {clock(limit)}. This one is{" "}
                {clock(picked?.seconds ?? 0)}.
              </p>
            ) : null}
            {sourceOptions.length === 0 && onOpenLibrary ? (
              <p className="m-0 text-muted-foreground text-sm">
                Nothing in the library yet. Add a recording, or make something first.
              </p>
            ) : null}
          </div>

          {tool === "separate" && stems.length > 0 ? (
            <fieldset className="m-0 grid gap-2 border-0 p-0" disabled={working}>
              <legend className="mb-1 font-semibold text-ui-lg">Keep these parts</legend>
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                {stems.map((name) => (
                  <Checkbox
                    key={name}
                    label={name}
                    checked={wanted.includes(name)}
                    disabled={working}
                    onCheckedChange={(on) =>
                      setKept(on ? [...wanted, name] : wanted.filter((x) => x !== name))
                    }
                  />
                ))}
              </div>
            </fieldset>
          ) : null}

          {tool === "convert" ? (
            <div className="grid gap-2">
              <Label htmlFor="convert-voice" className="font-semibold text-ui-lg">
                Sound like
              </Label>
              <Select
                id="convert-voice"
                value={voice || undefined}
                placeholder={voices.length ? "Choose a voice…" : "No saved voices yet"}
                disabled={working || voices.length === 0}
                options={voices.map((v) => ({ value: v.id, label: v.name }))}
                onValueChange={setVoice}
              />
              {voices.length === 0 ? (
                <p className="m-0 text-muted-foreground text-sm">
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
                <p className="m-0 text-muted-foreground text-sm">
                  Only change a voice into your own, or into one you have permission to use.
                </p>
              )}
            </div>
          ) : null}

          {tool === "edit" ? (
            <div className="grid gap-3">
              <div className="flex items-center gap-2">
                <Label htmlFor="edit-before" className="font-semibold text-ui-lg">
                  What it says now
                </Label>
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
              <Label htmlFor="edit-after" className="font-semibold text-ui-lg">
                What it should say
              </Label>
              <Textarea
                id="edit-after"
                rows={3}
                value={after}
                disabled={working}
                placeholder="Change a few words in the text above"
                onChange={(e) => setAfter(e.target.value)}
              />
              <p className="m-0 text-muted-foreground text-sm">
                Change a few words at a time: up to {chosen?.speech_edit?.max_changes ?? 5} separate
                changes. English and Chinese work best.
              </p>
            </div>
          ) : null}
        </>
      }
      action={
        <>
          <Button
            type="button"
            size="lg"
            className="w-full rounded-full md:w-auto md:px-10"
            onClick={() => void run()}
            disabled={!ready || !source || working || missing || tooLong}
          >
            {working ? <Spinner /> : null}
            {text.button}
          </Button>
          {!ready && chosen ? (
            <p className="mt-2 text-muted-foreground text-xs">
              <NotReadyText task={tool} seeAbove />
            </p>
          ) : speed && picked && !working ? (
            <p className="mt-2 text-muted-foreground text-xs">
              About {Math.max(1, Math.round(picked.seconds / speed))} seconds of work on this
              computer, plus a few to load the model.
            </p>
          ) : null}
        </>
      }
      stage={<Stage state={stage} className="w-full" minHeight="min-h-[14rem]" />}
      recent={
        <RecentStrip
          title="Made here before"
          items={recent}
          onSeeAll={onOpenLibrary}
          empty="Nothing made here yet."
        />
      }
    />
  );
}
