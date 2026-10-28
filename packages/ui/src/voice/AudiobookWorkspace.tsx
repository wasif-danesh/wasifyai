"use client";

import {
  type BookChapter,
  type ParsedEvent,
  type SavedVoice,
  type Speech,
  type ToolTrack,
  type Track,
  type VoiceApi,
  makeAudiobook,
  makeSpeech,
} from "@wasifyai/client";
import { BookOpen, FolderOpen, Headphones, Pencil } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { Experts } from "../components/experts";
import { Input } from "../components/input";
import { Label } from "../components/label";
import { MakeScreen } from "../components/make-screen";
import { Player } from "../components/player";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Spinner } from "../components/spinner";
import { Stage, type StageState } from "../components/stage";
import { Stepper } from "../components/stepper";
import { Textarea } from "../components/textarea";
import { LoadingModels, ModelPicker, NotReadyText } from "./ModelPicker";
import { OptionFields, expertsSummary } from "./OptionFields";
import { type VoiceChoice, VoicesPanel } from "./VoicesPanel";
import { SAMPLE } from "./VoicesWorkspace";
import { clock, minutesText, pickModel, stepProgress } from "./format";
import { useElapsed } from "./use-elapsed";
import { useVoiceModels } from "./use-voice-models";

export const TEXT_ACCEPT = ".txt,.md,.markdown,text/plain,text/markdown";
const WHOLE_MAX_CHARS = 100_000;
const SPOKEN_CHARS_PER_SECOND = 13;
/** the waveform is read from the whole file: past this length the plain bar is kinder */
const WAVEFORM_UP_TO_S = 900;

export type AudiobookWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
  onOpenLibrary?: () => void;
  title?: string;
  lead?: string;
};

type Made = { tracks: (ToolTrack & { chapter?: number })[]; book: ToolTrack | null };
type View = "text" | "chapters" | "voice";
const STEPS = ["Text", "Chapters", "Voice"];

/**
 * An audiobook on the one make screen (ADR-0093, stage U6), in steps: the text, then its chapters on the stage to
 * read, rename, join or remove, then the voice from the voices panel. While it is read the stage says which
 * chapter it is on; each chapter is kept in Your music as soon as it is done, and the whole book can be one track
 * too. A failure or a stop leaves the chapters already made where they are.
 */
export function AudiobookWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
  onOpenLibrary,
  title: heading = "Audiobook",
  lead,
}: AudiobookWorkspaceProps) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [chapters, setChapters] = useState<BookChapter[]>([]);
  const [view, setView] = useState<View>("text");
  const [saved, setSaved] = useState<SavedVoice[]>([]);
  const [speeches, setSpeeches] = useState<Speech[]>([]);
  const [choice, setChoice] = useState<VoiceChoice | null>(null);
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [readTitles, setReadTitles] = useState(true);
  const [whole, setWhole] = useState(false);
  const [step, setStep] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [made, setMade] = useState<Made | null>(null);
  const [books, setBooks] = useState<Track[] | null>(null);
  const abort = useRef<AbortController | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const working = step !== null;
  const waited = useElapsed(working);

  const savedVoice =
    choice?.kind === "saved" ? (saved.find((v) => v.id === choice.id) ?? null) : null;
  const task = savedVoice ? savedVoice.kind : "speak";
  const { models, error, loading, reload } = useVoiceModels(api, task);
  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, task, modelId);
  const ready = chosen?.state === "ready";
  const builtInId =
    choice?.kind === "builtin" && chosen?.voices.some((v) => v.id === choice.id)
      ? choice.id
      : (chosen?.default_voice ?? null);
  const panelValue: VoiceChoice | null = savedVoice
    ? { kind: "saved", id: savedVoice.id }
    : builtInId
      ? { kind: "builtin", id: builtInId }
      : null;
  const chars = chapters.reduce((n, c) => n + c.text.length, 0);
  const wholeOk = chars <= WHOLE_MAX_CHARS;

  const loadBooks = () =>
    api
      .tracks({ limit: 200 })
      .then((all) => setBooks(all.filter((t) => t.mode === "audiobook" || t.mode === "chapter")))
      .catch(() => setBooks((b) => b ?? []));
  useEffect(() => () => abort.current?.abort(), []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: read once, when the screen opens
  useEffect(() => {
    void loadBooks();
    api
      .voices()
      .then(setSaved)
      .catch(() => undefined);
    api
      .speeches()
      .then(setSpeeches)
      .catch(() => undefined);
  }, [api]);

  async function plan() {
    setProblem(null);
    setMade(null);
    try {
      const p = await api.planBook(text);
      setChapters(p.chapters);
      setView("chapters");
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The chapters could not be found.");
    }
  }

  async function open(f: File) {
    const words = await f.text();
    setText(words);
    if (!title.trim()) setTitle(f.name.replace(/\.[^.]+$/, ""));
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
      const joined = `${a.text}\n\n${b.title}.\n\n${b.text}`;
      const merged = {
        ...a,
        text: joined,
        chars: joined.length,
        estimated_seconds: Math.round(joined.length / SPOKEN_CHARS_PER_SECOND),
      };
      return [...all.slice(0, i), merged, ...all.slice(i + 2)];
    });
  }

  function chooseVoice(next: VoiceChoice) {
    const wasSaved = choice?.kind === "saved";
    setChoice(next);
    if (wasSaved !== (next.kind === "saved")) {
      setModelId(null);
      setValues({});
    }
  }

  async function sample(c: VoiceChoice): Promise<string | null> {
    try {
      const r = await makeSpeech(
        runs,
        c.kind === "saved"
          ? { text: SAMPLE, savedVoice: c.id }
          : { text: SAMPLE, model: chosen?.id, voice: c.id },
        new AbortController().signal,
      );
      if (!r.ok) {
        setProblem(r.message);
        return null;
      }
      return r.speech.audio_url;
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be made.");
      return null;
    }
  }

  const chaptersOk = chapters.length > 0 && chapters.every((c) => c.text.trim());
  const canMake = chaptersOk && title.trim().length > 0 && ready && (!whole || wholeOk) && !working;

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
          ...(savedVoice
            ? { savedVoice: savedVoice.id }
            : builtInId && builtInId !== chosen.default_voice
              ? { voice: builtInId }
              : {}),
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
      void loadBooks();
    }
  }

  if (error) {
    return (
      <p role="alert" className="p-6 text-destructive">
        {error}
      </p>
    );
  }
  if (loading && models.length === 0) return <LoadingModels />;

  const speed = chosen?.measured.speed_x;
  const spokenSeconds = chars / SPOKEN_CHARS_PER_SECOND;
  const current = view === "text" ? 0 : view === "chapters" ? 1 : 2;

  const chapterEditor = (
    <ol aria-label="The chapters" className="m-0 grid w-full list-none gap-2 p-0 text-start">
      {chapters.map((c, i) => (
        <li key={`${i}-${c.chars}`} className="grid gap-2 rounded-lg border bg-background p-3">
          <div className="flex items-center gap-2">
            <Input
              aria-label={`Title of chapter ${i + 1}`}
              className="h-9 min-w-0 flex-1"
              value={c.title}
              maxLength={120}
              disabled={working || view !== "chapters"}
              onChange={(e) => edit(i, { title: e.target.value })}
            />
            <span className="text-muted-foreground text-xs tabular-nums">
              {clock(c.estimated_seconds)}
            </span>
            {view === "chapters" && i + 1 < chapters.length ? (
              <Button size="xs" variant="ghost" onClick={() => joinWithNext(i)}>
                Join with next
              </Button>
            ) : null}
            {view === "chapters" ? (
              <Button
                size="xs"
                variant="ghost"
                onClick={() => setChapters((all) => all.filter((_, j) => j !== i))}
              >
                Remove
              </Button>
            ) : null}
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
              disabled={working || view !== "chapters"}
              onChange={(e) => edit(i, { text: e.target.value })}
            />
          </details>
        </li>
      ))}
    </ol>
  );

  const results = made ? [...(made.book ? [made.book] : []), ...made.tracks] : [];
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
    ...(chapters.length > 0
      ? [
          {
            label: "Change the chapters",
            onSelect: () => {
              setMade(null);
              setView("chapters");
            },
            icon: <Pencil aria-hidden="true" />,
          },
        ]
      : []),
  ];

  const stage: StageState = working
    ? {
        kind: "working",
        label: "Reading your book aloud…",
        text: `${step} · ${clock(waited)}`,
        value: stepProgress(step),
        onStop: () => abort.current?.abort(),
      }
    : made
      ? {
          kind: "result",
          children: (
            <ul className="m-0 grid max-h-[calc(100dvh-22rem)] w-full list-none gap-3 overflow-auto p-0 text-start">
              {results.map((t) => (
                <li key={t.id} className="grid gap-1.5">
                  <span className="font-medium text-sm">{t.title}</span>
                  <Player
                    src={t.audio_url}
                    title={t.title}
                    duration={t.seconds}
                    waveform={t.seconds <= WAVEFORM_UP_TO_S}
                  />
                </li>
              ))}
            </ul>
          ),
          caption: (
            <span>
              {made.tracks.length} {made.tracks.length === 1 ? "chapter" : "chapters"}
              {made.book ? " and the whole book" : ""}, kept in Your music.
            </span>
          ),
          actions: resultActions,
        }
      : problem && chapters.length === 0
        ? { kind: "error", message: problem, onReset: () => setProblem(null) }
        : chapters.length > 0
          ? {
              kind: "result",
              children: chapterEditor,
              caption: (
                <div className="grid gap-1">
                  <span>
                    {chapters.length} chapters, about {clock(spokenSeconds)} of speech.{" "}
                    {view === "chapters"
                      ? "Rename, join or remove them, and open one to change its words."
                      : "Go back to Chapters to change them."}
                  </span>
                  {problem ? (
                    <p role="alert" className="m-0 text-destructive text-sm">
                      {problem}
                    </p>
                  ) : null}
                </div>
              ),
            }
          : {
              kind: "empty",
              icon: BookOpen,
              title: "The chapters appear here.",
              text: "Paste or open the text on the left, then press Find the chapters. You read them before anything is spoken.",
            };

  const recent: RecentItem[] = (books ?? []).slice(0, 24).map((t) => ({
    id: t.id,
    cover: (
      <span className="grid size-full place-items-center gap-0.5 bg-muted p-1 text-center">
        <Headphones className="size-4 text-muted-foreground" aria-hidden="true" />
        <span className="line-clamp-2 text-xs leading-tight">{t.title}</span>
      </span>
    ),
    label: `Open: ${t.title}`,
    current: results.length === 1 && results[0]?.id === t.id,
    onOpen: () => {
      if (working) return;
      setProblem(null);
      setMade({ tracks: [t], book: null });
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
      title={heading}
      lead={lead}
      ask={
        <>
          <Stepper
            steps={STEPS}
            current={current}
            onStep={(i) => !working && setView(i === 0 ? "text" : "chapters")}
          />
          {/* in the window the model button is in the top bar, so it is there at every step */}
          <ModelPicker
            models={models}
            task={task}
            value={chosen?.id ?? null}
            onChange={(id) => {
              setModelId(id);
              setValues({});
              onModelChosen?.(id);
            }}
            onGetModel={onGetModel}
            disabled={working}
          />
          {view === "text" ? (
            <>
              <div className="grid gap-2">
                <Label htmlFor="book-title" className="font-semibold text-ui-lg">
                  Title of the book
                </Label>
                <Input
                  id="book-title"
                  value={title}
                  maxLength={120}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <div className="flex items-center gap-2">
                  <Label htmlFor="book-text" className="font-semibold text-ui-lg">
                    The text
                  </Label>
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
                  rows={10}
                  className="min-h-48"
                  value={text}
                  placeholder={
                    "Paste the text here. Chapters start at lines like “Chapter 1” or “# Title”."
                  }
                  onChange={(e) => {
                    setText(e.target.value);
                    setChapters([]);
                  }}
                />
              </div>
            </>
          ) : null}

          {view === "chapters" ? (
            <p className="m-0 text-muted-foreground text-sm">
              Read the chapters on the right. Rename, join or remove them, then choose the voice.
            </p>
          ) : null}

          {view === "voice" ? (
            <>
              <VoicesPanel
                builtIn={savedVoice ? [] : (chosen?.voices ?? [])}
                saved={saved}
                value={panelValue}
                onChange={chooseVoice}
                speeches={speeches}
                modelId={chosen?.id ?? null}
                onSample={ready || savedVoice ? sample : undefined}
                disabled={working}
              />
              <Checkbox
                label="Say each chapter's title before it"
                checked={readTitles}
                disabled={working}
                onCheckedChange={setReadTitles}
              />
              <Checkbox
                label="Also make one track of the whole book"
                hint={!wholeOk ? "Only for books up to about two hours." : undefined}
                checked={whole}
                disabled={working || !wholeOk}
                onCheckedChange={setWhole}
              />
              {chosen && chosen.options.length > 0 ? (
                <Experts summary={expertsSummary(chosen.options)}>
                  <OptionFields
                    options={chosen.options}
                    values={values}
                    onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
                    disabled={working}
                  />
                </Experts>
              ) : null}
            </>
          ) : null}
        </>
      }
      action={
        view === "text" ? (
          mainButton("Find the chapters", () => void plan(), text.trim().length === 0 || working)
        ) : view === "chapters" ? (
          <div className="flex flex-wrap items-center gap-2">
            {mainButton("Next: the voice", () => setView("voice"), !chaptersOk || working)}
            <Button type="button" variant="ghost" onClick={() => setView("text")}>
              Back to the text
            </Button>
          </div>
        ) : (
          <>
            {mainButton("Make the audiobook", () => void make(), !canMake)}
            {!ready && chosen ? (
              <p className="mt-2 text-muted-foreground text-xs">
                <NotReadyText task="speak" />
              </p>
            ) : !title.trim() ? (
              <p className="mt-2 text-muted-foreground text-xs">Give the book a title first.</p>
            ) : speed && !working ? (
              <p className="mt-2 text-muted-foreground text-xs">
                About {minutesText(spokenSeconds / speed)} of work on this computer.
              </p>
            ) : null}
          </>
        )
      }
      stage={<Stage state={stage} className="w-full" minHeight="min-h-[14rem]" />}
      recent={
        <RecentStrip
          title="Recent books and chapters"
          items={recent}
          loading={books === null}
          onSeeAll={onOpenLibrary}
          empty="No audiobooks yet. Your first chapters will show up here."
        />
      }
    />
  );
}
