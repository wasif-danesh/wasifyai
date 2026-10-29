"use client";

import {
  type AudioSource,
  type DubFit,
  type DubLine,
  type DubScript,
  type ParsedEvent,
  type SavedVoice,
  type Speech,
  type Track,
  type VoiceApi,
  type VoiceFrom,
  dubScript,
  makeDub,
} from "@wasifyai/client";
import { AudioLines, FolderOpen, Languages, Pencil } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { Label } from "../components/label";
import { MakeScreen } from "../components/make-screen";
import { Player } from "../components/player";
import { RadioGroup } from "../components/radio-group";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Select } from "../components/select";
import { Spinner } from "../components/spinner";
import { Stage, type StageState } from "../components/stage";
import { Stepper } from "../components/stepper";
import { Textarea } from "../components/textarea";
import { LoadingModels, ModelPicker, NotReadyText } from "./ModelPicker";
import { type Library, SourcePicker } from "./SourcePicker";
import { clock, pickModel, stepProgress } from "./format";
import { useElapsed } from "./use-elapsed";
import { useVoiceModels } from "./use-voice-models";

export const LANGUAGE_NAMES: Record<string, string> = {
  bg: "Bulgarian", cs: "Czech", da: "Danish", de: "German", el: "Greek", en: "English",
  es: "Spanish", et: "Estonian", fi: "Finnish", fr: "French", hr: "Croatian", hu: "Hungarian",
  it: "Italian", ja: "Japanese", ko: "Korean", lt: "Lithuanian", lv: "Latvian", mt: "Maltese",
  nl: "Dutch", pl: "Polish", pt: "Portuguese", ro: "Romanian", ru: "Russian", sk: "Slovak",
  sl: "Slovenian", sv: "Swedish", uk: "Ukrainian", zh: "Chinese",
}; // biome-ignore format: a table

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
  title?: string;
  lead?: string;
};

const base = (code: string) => code.toLowerCase().split(/[-_]/)[0] ?? code;

/** The languages a model speaks, as two-letter codes; "multi" is every one the app can name. */
function spoken(languages: string[]): string[] {
  const codes = languages.map(base);
  return codes.includes("multi") ? Object.keys(LANGUAGE_NAMES) : codes;
}

const STEPS = ["Recording", "Language", "Script", "Voice"];
type View = "setup" | "script" | "voice";

/**
 * Dubbing on the one make screen (ADR-0093, stage U6), in steps so the person reads and changes the translation
 * before anything is spoken: the recording and the language, then the script on the stage, then the voice. The
 * voice is the original speaker's (copied, which needs the person's word that it is theirs or allowed), a voice
 * they saved, or a built-in one. The dub plays on the stage; the dubs made before are the recent strip.
 */
export function DubbingWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
  initialSource,
  onOpenLibrary,
  title = "Dub a recording",
  lead,
}: DubbingWorkspaceProps) {
  const [library, setLibrary] = useState<Library | null>(null);
  const [source, setSource] = useState<AudioSource | null>(initialSource ?? null);
  const [language, setLanguage] = useState("");
  const [keepBackground, setKeepBackground] = useState(true);
  const [voiceFrom, setVoiceFrom] = useState<VoiceFrom>("speaker");
  const [saved, setSaved] = useState<SavedVoice[]>([]);
  const [savedId, setSavedId] = useState("");
  const [builtin, setBuiltin] = useState("");
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [script, setScript] = useState<DubScript | null>(null);
  const [lines, setLines] = useState<DubLine[]>([]);
  const [view, setView] = useState<View>("setup");
  const [step, setStep] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [made, setMade] = useState<{
    track: Pick<Track, "id" | "title" | "seconds" | "audio_url">;
    fit: DubFit | null;
  } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const working = step !== null;
  const waited = useElapsed(working);

  const task = voiceFrom === "builtin" ? "speak" : "clone"; // copying a voice, saved or not, is "clone"
  const voices = useVoiceModels(api, task);
  const speakers = useVoiceModels(api, "speak");
  const clones = useVoiceModels(api, "clone");

  const loadLibrary = () =>
    Promise.all([api.tracks({ limit: 200 }), api.speeches(200)])
      .then(([tracks, speeches]) => setLibrary({ tracks, speeches }))
      .catch(() => setLibrary((l) => l ?? { tracks: [], speeches: [] }));
  useEffect(() => () => abort.current?.abort(), []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: read once, when the screen opens
  useEffect(() => {
    void loadLibrary();
    api
      .voices()
      .then(setSaved)
      .catch(() => undefined);
  }, [api]);

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

  const voiceOk =
    voiceFrom === "speaker"
      ? script?.vocalsTrack !== undefined
      : voiceFrom === "saved"
        ? savedId !== ""
        : true;
  const readyToWrite = source !== null && language !== "" && !working;
  const linesOk = lines.length > 0 && lines.every((l) => l.text.trim());
  const readyToMake = script !== null && linesOk && voiceOk && ready && !working;

  function restart() {
    setScript(null);
    setMade(null);
    setView("setup");
  }

  async function addFile(file: File) {
    setProblem(null);
    try {
      const t = await api.importTrack(file);
      setLibrary((l) => ({ tracks: [t, ...(l?.tracks ?? [])], speeches: l?.speeches ?? [] }));
      setSource({ kind: "track", id: t.id });
      restart();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That recording could not be added.");
    }
  }

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
        setView("script");
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
      if (r.ok) {
        setMade({ track: r.track, fit: r.fit });
        void loadLibrary();
      } else setProblem(r.message);
    } catch (e) {
      if (!signal.aborted) setProblem(e instanceof Error ? e.message : "That could not be made.");
    } finally {
      setStep(null);
      void voices.reload();
    }
  }

  if (voices.error) {
    return (
      <p role="alert" className="p-6 text-destructive">
        {voices.error}
      </p>
    );
  }
  if (library === null || voices.loading || speakers.loading || clones.loading) {
    return <LoadingModels />;
  }

  const builtinVoices = chosen?.voices ?? [];
  const current = view === "setup" ? (source ? 1 : 0) : view === "script" ? 2 : 3;

  const scriptEditor = (
    <ol aria-label="The script" className="m-0 grid w-full list-none gap-3 p-0 text-start">
      {lines.map((l, i) => (
        <li key={`${l.start}-${l.end}`} className="grid gap-1 rounded-lg border bg-background p-3">
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
            disabled={working || view === "voice"}
            onChange={(e) =>
              setLines((all) => all.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))
            }
          />
        </li>
      ))}
    </ol>
  );

  const resultActions: Action[] = [
    ...(onOpenLibrary
      ? [
          {
            label: "Open Your music",
            onSelect: onOpenLibrary,
            icon: <FolderOpen aria-hidden="true" />,
          },
        ]
      : []),
    ...(script
      ? [
          {
            label: "Change the script",
            onSelect: () => {
              setMade(null);
              setView("script");
            },
            icon: <Pencil aria-hidden="true" />,
          },
        ]
      : []),
  ];

  const stage: StageState = working
    ? {
        kind: "working",
        label: script ? "Making the dub…" : "Writing the script…",
        text: `${step} · ${clock(waited)}`,
        value: stepProgress(step),
        onStop: () => abort.current?.abort(),
      }
    : made
      ? {
          kind: "result",
          children: (
            <Player
              key={made.track.id}
              className="w-full"
              src={made.track.audio_url}
              title={made.track.title}
              duration={made.track.seconds}
              waveform
            />
          ),
          caption: (
            <div className="grid gap-1">
              <span className="text-foreground">{made.track.title}</span>
              {made.fit ? (
                <span className="text-xs">
                  {made.fit.lines} lines
                  {made.fit.sped_up > 0
                    ? `, ${made.fit.sped_up} played a little faster to fit their time`
                    : ""}
                  {made.fit.max_overflow_s > 0.3
                    ? `. One line runs ${made.fit.max_overflow_s.toFixed(1)} seconds past its place: shorten it in the script and make the dub again.`
                    : "."}{" "}
                  It is kept in Your music.
                </span>
              ) : (
                <span className="text-xs">{clock(made.track.seconds)} · kept in Your music</span>
              )}
            </div>
          ),
          actions: resultActions,
        }
      : script
        ? {
            kind: "result",
            children: scriptEditor,
            caption: (
              <div className="grid gap-1">
                <span>
                  {lines.length} lines in {LANGUAGE_NAMES[language] ?? language}.{" "}
                  {view === "script"
                    ? "Change any line; the times stay."
                    : "Go back to Script to change a line."}
                </span>
                {problem ? (
                  <p role="alert" className="m-0 text-destructive text-sm">
                    {problem}
                  </p>
                ) : null}
              </div>
            ),
          }
        : problem
          ? { kind: "error", message: problem, onReset: () => setProblem(null) }
          : {
              kind: "empty",
              icon: Languages,
              title: "The script appears here.",
              text: "Choose a recording and a language, then press Write the script. You read it before anything is spoken.",
            };

  const recent: RecentItem[] = library.tracks
    .filter((t) => t.mode === "dubbed")
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
      current: made?.track.id === t.id,
      onOpen: () => {
        if (working) return;
        setProblem(null);
        setMade({ track: t, fit: null });
      },
    }));

  const mainButton = (label: string, onClick: () => void, disabled: boolean) => (
    <Button
      type="button"
      size="lg"
      className="w-full rounded-full md:w-auto md:px-10"
      disabled={disabled}
      onClick={onClick}
    >
      {working ? <Spinner /> : null}
      {label}
    </Button>
  );

  return (
    <MakeScreen
      title={title}
      lead={lead}
      ask={
        <>
          <Stepper
            steps={STEPS}
            current={current}
            onStep={(i) => {
              if (working) return;
              if (i <= 1) setView("setup");
              else if (i === 2) setView("script");
            }}
          />
          {/* in the window the model button is in the top bar, so it is there at every step */}
          {usable.length > 0 ? (
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
          ) : null}
          {view === "setup" ? (
            <>
              <SourcePicker
                id="dub-source"
                label="Which recording?"
                library={library}
                value={source}
                disabled={working}
                onAdd={(f) => void addFile(f)}
                onChange={(next) => {
                  setSource(next);
                  restart();
                }}
              />
              {library.tracks.length + library.speeches.length === 0 && onOpenLibrary ? (
                <p className="m-0 text-muted-foreground text-sm">
                  Nothing in the library yet. Add a recording, or{" "}
                  <button
                    type="button"
                    className="underline underline-offset-4"
                    onClick={onOpenLibrary}
                  >
                    open Your music
                  </button>
                  .
                </p>
              ) : null}
              <div className="grid gap-2">
                <Label htmlFor="dub-language" className="font-semibold text-ui-lg">
                  Dub it into
                </Label>
                <Select
                  id="dub-language"
                  value={language || undefined}
                  placeholder="Choose a language…"
                  disabled={working}
                  options={languages.map((c) => ({ value: c, label: LANGUAGE_NAMES[c] ?? c }))}
                  onValueChange={(c) => {
                    setLanguage(c);
                    restart();
                  }}
                />
              </div>
              <Checkbox
                label="Keep the music and sounds behind the voice"
                checked={keepBackground}
                disabled={working}
                onCheckedChange={setKeepBackground}
              />
            </>
          ) : null}

          {view === "script" ? (
            <p className="m-0 text-muted-foreground text-sm">
              Read the script on the right and change any line you like. Then choose the voice.
            </p>
          ) : null}

          {view === "voice" ? (
            <>
              <RadioGroup
                label="Whose voice"
                value={voiceFrom}
                disabled={working}
                onValueChange={(v) => setVoiceFrom(v as VoiceFrom)}
                options={[
                  {
                    value: "speaker",
                    label: "The original speaker's voice, copied from the recording",
                  },
                  { value: "saved", label: "A voice I saved" },
                  {
                    value: "builtin",
                    label: "A built-in voice",
                    hint: "Not every language has one.",
                  },
                ]}
              />
              {voiceFrom === "speaker" && !script?.vocalsTrack ? (
                <p className="m-0 text-destructive text-sm">
                  Write the script again: the voice has to be separated to be copied.
                </p>
              ) : null}
              {voiceFrom === "saved" ? (
                <Select
                  aria-label="Saved voice"
                  value={savedId || undefined}
                  placeholder={savedUsable.length ? "Choose a voice…" : "No saved voices yet"}
                  disabled={working || savedUsable.length === 0}
                  options={savedUsable.map((v) => ({ value: v.id, label: v.name }))}
                  onValueChange={setSavedId}
                />
              ) : null}
              {usable.length === 0 ? (
                <p role="alert" className="m-0 text-destructive text-sm">
                  No voice model speaks {LANGUAGE_NAMES[language] ?? language} this way. Get one in
                  the Model hub or choose another voice.
                </p>
              ) : null}
              {voiceFrom === "builtin" && builtinVoices.length > 0 ? (
                <Select
                  aria-label="Built-in voice"
                  value={builtin || "usual"}
                  disabled={working}
                  options={[
                    { value: "usual", label: "The model's usual voice" },
                    ...builtinVoices.map((v) => ({ value: v.id, label: v.label })),
                  ]}
                  onValueChange={(v) => setBuiltin(v === "usual" ? "" : v)}
                />
              ) : null}
            </>
          ) : null}
        </>
      }
      action={
        view === "setup" ? (
          mainButton("Write the script", () => void write(), !readyToWrite)
        ) : view === "script" ? (
          <div className="flex flex-wrap items-center gap-2">
            {mainButton("Next: the voice", () => setView("voice"), working || !linesOk)}
            <Button type="button" variant="ghost" disabled={working} onClick={restart}>
              Start again
            </Button>
          </div>
        ) : (
          <>
            {mainButton("Make the dub", () => void make(), !readyToMake)}
            {!ready && chosen ? (
              <p className="mt-2 text-muted-foreground text-xs">
                <NotReadyText task="dub" />
              </p>
            ) : null}
          </>
        )
      }
      stage={<Stage state={stage} className="w-full" minHeight="min-h-[14rem]" />}
      recent={
        <RecentStrip
          title="Recent dubs"
          items={recent}
          onSeeAll={onOpenLibrary}
          empty="No dubs yet. Your first one will show up here."
        />
      }
    />
  );
}
