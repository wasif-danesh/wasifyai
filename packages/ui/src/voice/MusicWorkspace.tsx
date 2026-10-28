"use client";

import {
  type MusicMode,
  type MusicModeRules,
  type MusicRequest,
  type ParsedEvent,
  type Track,
  type VoiceApi,
  makeTrack,
} from "@wasifyai/client";
import { Heart, Music, Pencil, RefreshCw, Save, Scissors, Shuffle, Trash2 } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { Chip } from "../components/chip";
import { ConfirmDialog, NameDialog } from "../components/dialog";
import { Experts } from "../components/experts";
import { Input } from "../components/input";
import { Label } from "../components/label";
import { MakeScreen } from "../components/make-screen";
import { Player } from "../components/player";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Segmented } from "../components/segmented";
import { Slider } from "../components/slider";
import { Spinner } from "../components/spinner";
import { Stage, type StageState } from "../components/stage";
import { Textarea } from "../components/textarea";
import { fileNameFor, savedText, useSaveCopy } from "../save";
import { appearsHere, makingLabel } from "../words";
import { EditTrack } from "./EditTrack";
import { LyricsWriter } from "./LyricsWriter";
import { LoadingModels, ModelPicker, NotReadyText } from "./ModelPicker";
import { OptionFields, expertsSummary } from "./OptionFields";
import { RuntimeCard } from "./RuntimeCard";
import { trackKind } from "./TrackList";
import { clock, pickModel } from "./format";
import { useElapsed } from "./use-elapsed";
import { useVoiceModels } from "./use-voice-models";

export type MusicWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
  /** lyrics written elsewhere (the Lyrics screen) */
  initialLyrics?: string | null;
  /** something to do with a track as the screen opens: it was chosen on Your music */
  initialAction?: { kind: "edit" | "again" | "take"; trackId: string } | null;
  /** take a track to Split into parts (the app opens that screen with it chosen) */
  onSplit?: (track: Track) => void;
  /** "See all" on the recent strip */
  onOpenLibrary?: () => void;
  title?: string;
  lead?: string;
};

const MODE_TEXT: Record<
  MusicMode,
  { label: string; ask: string; hint: string; make: string; noun: "song" | "sound" }
> = {
  song: {
    label: "Song",
    ask: "Describe the song",
    hint: "Style, mood, instruments. For example: upbeat pop, female vocals, summer",
    make: "Make the song",
    noun: "song",
  },
  sfx: {
    label: "Sound effect",
    ask: "Describe the sound",
    hint: "For example: rain on a tin roof, distant thunder",
    make: "Make the sound",
    noun: "sound",
  },
};

/** One click adds a style to the description, and another takes it out again. */
const STYLES: Record<MusicMode, string[]> = {
  song: ["pop", "rock", "lo-fi", "electronic", "orchestral", "jazz", "acoustic", "hip-hop", "folk", "ambient"],
  sfx: ["rain", "wind", "footsteps", "crowd", "birds", "door", "engine", "water"],
}; // biome-ignore format: a list

const MUSIC_MODES = new Set(["song", "sfx", "edit"]);

function hasWord(text: string, word: string): boolean {
  return text
    .toLowerCase()
    .split(/,\s*/)
    .some((part) => part.trim() === word);
}

function toggleWord(text: string, word: string): string {
  if (hasWord(text, word)) {
    return text
      .split(/,\s*/)
      .filter((part) => part.trim().toLowerCase() !== word)
      .join(", ");
  }
  return text.trim() ? `${text.trim().replace(/,$/, "")}, ${word}` : word;
}

/**
 * Music on the one make screen (ADR-0093, stage U7). What the ask column offers comes from the model the person
 * picks: style chips and a description, a lyrics panel only if it sings (written by the chat model or pasted), a
 * switch for leaving the singing out only if it can, the lengths it makes; tempo, key, seed and how many are under
 * "For experts". The song plays on the stage with its lyrics and three actions and a menu; the music made before
 * is the recent strip, and changing a part of a piece opens on the stage.
 */
export function MusicWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
  initialLyrics,
  initialAction,
  onSplit,
  onOpenLibrary,
  title = "Create music",
  lead,
}: MusicWorkspaceProps) {
  const descId = useId();
  const lyricsId = useId();
  const { models, runtime, error, loading, reload } = useVoiceModels(api, "music");
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [modeChoice, setModeChoice] = useState<MusicMode | null>(null);
  const [description, setDescription] = useState("");
  const [lyrics, setLyrics] = useState(initialLyrics ?? "");
  const [instrumental, setInstrumental] = useState(false);
  const [seconds, setSeconds] = useState<number | null>(null);
  const [seed, setSeed] = useState("");
  const [takes, setTakes] = useState(1);
  const [writing, setWriting] = useState(false);
  const [editing, setEditing] = useState<Track | null>(null);
  const [take, setTake] = useState<[number, number] | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [step, setStep] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [formats, setFormats] = useState<string[]>(["wav"]);
  const [shownId, setShownId] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<Track | null>(null);
  const [deleting, setDeleting] = useState<Track | null>(null);
  const abort = useRef<AbortController | null>(null);
  const working = step !== null;
  const waited = useElapsed(working);

  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, "music", modelId);
  const listed = (Object.keys(chosen?.music?.modes ?? {}) as string[]).filter(
    (m): m is MusicMode => m === "song" || m === "sfx",
  ); // "edit" is not something to make: it changes a track (EditTrack)
  // a model that does not say what it makes (or no model yet) still gets the song form: the prompt box is there
  // from the start, never a blank screen (ADR-0093, stage U7)
  const modes: MusicMode[] = listed.length > 0 ? listed : ["song"];
  const mode: MusicMode | null =
    modeChoice && modes.includes(modeChoice) ? modeChoice : (modes[0] ?? null);
  const rules: MusicModeRules | null = (mode && chosen?.music.modes?.[mode]) || null;
  const [lo, usual, hi] = rules?.duration ?? [1, 30, 60];
  const length = Math.max(lo, Math.min(hi, seconds ?? usual));
  const sings = mode === "song" && rules?.lyrics !== "unused";
  const canSkipSinging = mode === "song" && rules?.instrumental === "toggle";
  const ready = chosen?.state === "ready";

  const loadTracks = useCallback(
    () =>
      api
        .tracks({ limit: 200 })
        .then((all) => setTracks(all.filter((t) => MUSIC_MODES.has(t.mode))))
        .catch(() => setTracks((t) => t ?? [])),
    [api],
  );
  useEffect(() => {
    void loadTracks();
    api
      .formats()
      .then((f) => Array.isArray(f) && f.length > 0 && setFormats(f))
      .catch(() => undefined);
  }, [api, loadTracks]);
  useEffect(() => () => abort.current?.abort(), []);
  // an action chosen on Your music runs once, when the models are known
  const acted = useRef(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: once, when the models have loaded
  useEffect(() => {
    if (!initialAction || acted.current || loading) return;
    acted.current = true;
    api
      .track(initialAction.trackId)
      .then((t) => {
        if (initialAction.kind === "edit") setEditing(t);
        else again(t, initialAction.kind === "again");
      })
      .catch(() => setProblem("That piece of music is no longer there."));
  }, [loading]);

  /** Make `count` pieces from one request. With a seed, the takes use that seed and the ones after it;
   * without, each gets its own. */
  async function begin(request: MusicRequest, count: number) {
    setProblem(null);
    setNote(null);
    setEditing(null);
    setStep("Starting");
    abort.current = new AbortController();
    try {
      for (let i = 0; i < count; i++) {
        setTake([i + 1, count]);
        const seeded =
          request.seed !== undefined ? { ...request, seed: request.seed + i } : request;
        const r = await makeTrack(runs, seeded, abort.current.signal, setStep);
        if (!r.ok) {
          setProblem(r.message);
          break;
        }
        setShownId(r.track.id);
        await loadTracks();
      }
    } catch (e) {
      if (!abort.current.signal.aborted) {
        setProblem(e instanceof Error ? e.message : "That could not be made.");
      }
    } finally {
      setStep(null);
      setTake(null);
      void reload();
    }
  }

  function make() {
    if (!chosen || !mode || working) return;
    const options = Object.fromEntries(
      Object.entries(values).filter(
        ([k, v]) => v !== undefined && v !== "" && chosen.options.some((o) => o.name === k),
      ),
    );
    void begin(
      {
        description,
        model: chosen.id,
        mode,
        lyrics: sings && !instrumental ? lyrics : undefined,
        instrumental: canSkipSinging && instrumental,
        duration: length,
        seed: seed.trim() === "" ? undefined : Number(seed),
        options,
      },
      takes,
    );
  }

  /** Make a piece again from a track's own settings: the same seed gives the same music, a new one
   * another take. The form shows what was used. */
  function again(t: Track, sameSeed: boolean) {
    if (working || (t.mode !== "song" && t.mode !== "sfx")) return;
    const m = models.find((x) => x.id === t.model_id);
    if (!m || m.state !== "ready") {
      setProblem(`${m?.title ?? "That model"} is not ready. Choose a model that is ready.`);
      return;
    }
    setModelId(m.id);
    setModeChoice(t.mode);
    setDescription(t.description);
    setLyrics(t.lyrics);
    setInstrumental(t.instrumental);
    setSeconds(t.seconds);
    setSeed(sameSeed && t.seed !== null ? String(t.seed) : "");
    setValues(t.options);
    void begin(
      {
        description: t.description,
        model: m.id,
        mode: t.mode,
        lyrics: t.lyrics || undefined,
        instrumental: t.instrumental,
        duration: t.seconds,
        seed: sameSeed && t.seed !== null ? t.seed : undefined,
        options: t.options,
      },
      1,
    );
  }

  const saveCopy = useSaveCopy();
  async function save(t: Track, format: "wav" | "mp3" | "m4a") {
    setProblem(null);
    try {
      const out = await saveCopy({
        name: fileNameFor(t.title, format, "music"),
        blob: () => api.downloadTrack(t.id, format),
      });
      if (out) setNote(savedText(out));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be saved.");
    }
  }

  const change = (saved: Track) =>
    setTracks((list) => (list ?? []).map((x) => (x.id === saved.id ? saved : x)));

  async function rename(t: Track, next: string) {
    setRenaming(null);
    try {
      change(await api.updateTrack(t.id, { title: next }));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be renamed.");
    }
  }

  async function heart(t: Track) {
    try {
      change(await api.updateTrack(t.id, { favourite: !t.favourite }));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That did not work.");
    }
  }

  async function remove(t: Track) {
    setDeleting(null);
    try {
      await api.removeTrack(t.id);
      setTracks((list) => (list ?? []).filter((x) => x.id !== t.id));
      if (shownId === t.id) setShownId(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be deleted.");
    }
  }

  if (error) {
    return (
      <p role="alert" className="p-6 text-destructive">
        {error}
      </p>
    );
  }
  if (loading) return <LoadingModels />;

  const speed = chosen?.measured.speed_x;
  const shown = (tracks ?? []).find((t) => t.id === shownId) ?? null;
  const modelTitle = (id: string) => models.find((m) => m.id === id)?.title ?? id;
  const best = (formats.includes("mp3") ? "mp3" : "wav") as "wav" | "mp3";
  const madeHere = shown && (shown.mode === "song" || shown.mode === "sfx");

  const actions: Action[] = shown
    ? [
        {
          label: "Save a copy",
          onSelect: () => void save(shown, best),
          icon: <Save aria-hidden="true" />,
        },
        ...(madeHere
          ? [
              {
                label: "Make it again",
                onSelect: () => again(shown, true),
                disabled: working,
                icon: <RefreshCw aria-hidden="true" />,
              },
              {
                label: "Another take",
                onSelect: () => again(shown, false),
                disabled: working,
                icon: <Shuffle aria-hidden="true" />,
              },
            ]
          : []),
        {
          label: "Change a part",
          onSelect: () => setEditing(shown),
          icon: <Pencil aria-hidden="true" />,
        },
        ...(onSplit
          ? [
              {
                label: "Split into parts",
                onSelect: () => onSplit(shown),
                icon: <Scissors aria-hidden="true" />,
              },
            ]
          : []),
        ...formats
          .filter((f) => f !== best && (f === "wav" || f === "mp3" || f === "m4a"))
          .map((f) => ({
            label: `Save as ${f.toUpperCase()}`,
            onSelect: () => void save(shown, f as "wav" | "mp3" | "m4a"),
          })),
        {
          label: shown.favourite ? "Remove from favourites" : "Add to favourites",
          onSelect: () => void heart(shown),
          icon: <Heart aria-hidden="true" />,
        },
        { label: "Rename", onSelect: () => setRenaming(shown) },
        {
          label: "Delete",
          onSelect: () => setDeleting(shown),
          icon: <Trash2 aria-hidden="true" />,
          destructive: true,
        },
      ]
    : [];

  const stage: StageState = working
    ? {
        kind: "working",
        label: mode === "sfx" ? "Making your sound…" : makingLabel("song"),
        text: [take && take[1] > 1 ? `Take ${take[0]} of ${take[1]}` : null, step, clock(waited)]
          .filter(Boolean)
          .join(" · "),
        onStop: () => abort.current?.abort(),
      }
    : editing
      ? {
          kind: "result",
          children: (
            <div className="w-full text-start">
              <EditTrack
                api={api}
                runs={runs}
                track={editing}
                models={models}
                onGetModel={onGetModel}
                onDone={(id) => {
                  setEditing(null);
                  setShownId(id || null);
                  void loadTracks();
                }}
                onClose={() => setEditing(null)}
              />
            </div>
          ),
        }
      : problem && !shown
        ? { kind: "error", message: problem, onReset: () => setProblem(null) }
        : shown
          ? {
              kind: "result",
              children: (
                <Player
                  key={shown.id}
                  className="w-full"
                  src={shown.audio_url}
                  title={shown.title}
                  duration={shown.seconds}
                  waveform
                />
              ),
              caption: (
                <div className="grid gap-1.5">
                  <span className="text-foreground">
                    {shown.title}
                    {shown.favourite ? " ♥" : ""}{" "}
                    <span className="text-muted-foreground text-xs">
                      {trackKind(shown)} · {clock(shown.seconds)} · {modelTitle(shown.model_id)}
                    </span>
                  </span>
                  {shown.description ? <span className="text-xs">{shown.description}</span> : null}
                  {shown.lyrics ? (
                    <pre className="m-0 max-h-40 overflow-auto whitespace-pre-wrap rounded-md border bg-background p-2 font-sans text-foreground text-xs">
                      {shown.lyrics}
                    </pre>
                  ) : null}
                  {note ? <output className="text-sm">{note}</output> : null}
                  {problem ? (
                    <p role="alert" className="m-0 text-destructive text-sm">
                      {problem}
                    </p>
                  ) : null}
                </div>
              ),
              actions,
            }
          : {
              kind: "empty",
              icon: Music,
              title: mode === "sfx" ? "Your sound appears here." : appearsHere("song"),
              text: `Describe it on the left, then press ${mode ? MODE_TEXT[mode].make : "Make the song"}.`,
            };

  const recent: RecentItem[] = (tracks ?? []).slice(0, 24).map((t) => ({
    id: t.id,
    cover: (
      <span className="grid size-full place-items-center gap-0.5 bg-muted p-1 text-center">
        <Music className="size-4 text-muted-foreground" aria-hidden="true" />
        <span className="line-clamp-2 text-[0.625rem] leading-tight">{t.title}</span>
      </span>
    ),
    label: `Open: ${t.title}`,
    current: t.id === shownId,
    onOpen: () => {
      if (working) return;
      setProblem(null);
      setNote(null);
      setEditing(null);
      setShownId(t.id);
    },
  }));

  const expertsBits = [chosen ? expertsSummary(chosen.options) : "", "seed", "how many"].filter(
    Boolean,
  );

  return (
    <>
      <MakeScreen
        title={title}
        lead={lead}
        ask={
          <>
            {runtime ? <RuntimeCard runtime={runtime} api={api} onChanged={reload} /> : null}
            <ModelPicker
              models={models}
              task="music"
              value={chosen?.id ?? null}
              onChange={(id) => {
                setModelId(id);
                setModeChoice(null);
                setSeconds(null);
                setValues({});
                onModelChosen?.(id);
              }}
              onGetModel={onGetModel}
              disabled={working}
            />
            {modes.length > 1 && mode ? (
              <Segmented
                label="What to make"
                value={mode}
                onValueChange={(m) => setModeChoice(m as MusicMode)}
                options={modes.map((m) => ({ value: m, label: MODE_TEXT[m].label }))}
              />
            ) : null}
            {mode ? (
              <>
                <div className="grid gap-2">
                  <Label htmlFor={descId} className="font-semibold text-ui-lg">
                    {MODE_TEXT[mode].ask}
                  </Label>
                  <Textarea
                    id={descId}
                    rows={3}
                    value={description}
                    maxLength={500}
                    placeholder={MODE_TEXT[mode].hint}
                    disabled={working}
                    onChange={(e) => setDescription(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault();
                        make();
                      }
                    }}
                  />
                  <fieldset className="m-0 flex flex-wrap gap-1.5 border-0 p-0">
                    <legend className="sr-only">Styles</legend>
                    {STYLES[mode].map((w) => (
                      <Chip
                        key={w}
                        aria-pressed={hasWord(description, w)}
                        disabled={working}
                        onClick={() => setDescription((d) => toggleWord(d, w))}
                      >
                        {w}
                      </Chip>
                    ))}
                  </fieldset>
                </div>
                {canSkipSinging ? (
                  <Checkbox
                    label="No singing (instrumental)"
                    checked={instrumental}
                    disabled={working}
                    onCheckedChange={setInstrumental}
                  />
                ) : mode === "song" && rules?.instrumental === "always" ? (
                  <p className="m-0 text-muted-foreground text-sm">
                    This model makes music without singing.
                  </p>
                ) : null}
                {sings && !instrumental ? (
                  <section className="grid gap-2 rounded-md border p-3" aria-label="Lyrics">
                    <div className="flex items-center gap-2">
                      <Label htmlFor={lyricsId} className="font-semibold text-ui-lg">
                        Lyrics{" "}
                        <span className="font-normal text-muted-foreground">
                          {rules?.lyrics === "required" ? "(needed)" : "(optional)"}
                        </span>
                      </Label>
                      <Button
                        size="xs"
                        variant="outline"
                        className="ms-auto"
                        disabled={working}
                        onClick={() => setWriting((w) => !w)}
                      >
                        {writing ? "Close the writer" : "Write them for me"}
                      </Button>
                    </div>
                    {writing ? (
                      <LyricsWriter
                        runs={runs}
                        style={description || undefined}
                        duration={length}
                        initial={lyrics}
                        onUse={(words) => {
                          setLyrics(words);
                          setWriting(false);
                        }}
                      />
                    ) : null}
                    <Textarea
                      id={lyricsId}
                      rows={5}
                      value={lyrics}
                      maxLength={5000}
                      placeholder={
                        "[verse]\nWrite or paste the words, one line at a time\n[chorus]\n…"
                      }
                      disabled={working}
                      onChange={(e) => setLyrics(e.target.value)}
                    />
                  </section>
                ) : null}
                <div className="grid gap-1.5">
                  <span aria-hidden="true" className="font-semibold text-ui-lg">
                    Length
                  </span>
                  <Slider
                    label="Length"
                    min={lo}
                    max={hi}
                    step={1}
                    value={length}
                    format={(v) => clock(v)}
                    disabled={working}
                    onValueChange={setSeconds}
                  />
                </div>
                <Experts summary={expertsBits.join(", ")}>
                  {chosen ? (
                    <OptionFields
                      options={chosen.options}
                      values={values}
                      onChange={(name, v) => setValues((prev) => ({ ...prev, [name]: v }))}
                      disabled={working}
                    />
                  ) : null}
                  <div className="grid gap-1.5">
                    <Label htmlFor="music-seed">Seed</Label>
                    <Input
                      id="music-seed"
                      type="number"
                      min={0}
                      className="w-40"
                      value={seed}
                      placeholder="a new one each time"
                      disabled={working}
                      onChange={(e) => setSeed(e.target.value)}
                    />
                    <p className="m-0 text-muted-foreground text-xs">
                      The same seed and words give the same music. With several, each uses the next
                      seed.
                    </p>
                  </div>
                  <Segmented
                    label="How many"
                    value={String(takes)}
                    onValueChange={(v) => setTakes(Number(v))}
                    options={[1, 2, 3, 4].map((n) => ({ value: String(n), label: String(n) }))}
                  />
                </Experts>
              </>
            ) : null}
          </>
        }
        action={
          <>
            <Button
              type="button"
              size="lg"
              className="w-full rounded-full md:w-auto md:px-10"
              disabled={!ready || working || !mode || description.trim().length < 3}
              title="Ctrl or ⌘ + Enter makes it too"
              aria-keyshortcuts="Control+Enter Meta+Enter"
              onClick={make}
            >
              {working ? <Spinner /> : null}
              {mode ? MODE_TEXT[mode].make : "Make the song"}
              {takes > 1 ? ` (${takes})` : ""}
            </Button>
            {!ready && chosen ? (
              <p className="mt-2 text-muted-foreground text-xs">
                <NotReadyText task="music" seeAbove />
              </p>
            ) : !working ? (
              <p className="mt-2 text-muted-foreground text-xs">
                {speed
                  ? `About ${Math.max(1, Math.round(length / speed))} seconds of work on this computer.`
                  : "Music takes a while: from under a minute to several, depending on the model and the length."}
              </p>
            ) : null}
          </>
        }
        stage={<Stage state={stage} className="w-full" minHeight="min-h-[14rem]" />}
        recent={
          <RecentStrip
            title="Recent music"
            items={recent}
            loading={tracks === null}
            onSeeAll={onOpenLibrary}
            empty="No music yet. Your first song will show up here."
          />
        }
      />
      {renaming ? (
        <NameDialog
          title="Name this piece"
          label="Name"
          initial={renaming.title}
          onSubmit={(next) => void rename(renaming, next)}
          onCancel={() => setRenaming(null)}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title="Delete this piece?"
          message={`“${deleting.title}” is deleted for good.`}
          onConfirm={() => void remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      ) : null}
    </>
  );
}
