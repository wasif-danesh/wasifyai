"use client";

import {
  type AddedPicture,
  type AudioSource,
  type Clip,
  type ClipShape,
  type LipSyncEngine,
  type ParsedEvent,
  type VoiceApi,
  clipFrame,
  makeClip,
} from "@wasifyai/client";
import { Film, Pencil, Save, Trash2, UserRound } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { ConfirmDialog, NameDialog } from "../components/dialog";
import { Label } from "../components/label";
import { MakeScreen } from "../components/make-screen";
import { Bar } from "../components/progress-bar";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Segmented } from "../components/segmented";
import { Spinner } from "../components/spinner";
import { Stage, type StageState } from "../components/stage";
import { Stepper } from "../components/stepper";
import { Textarea } from "../components/textarea";
import { useChoicesFor } from "../models";
import { formatBytes } from "../notebook/format";
import { fileNameFor, savedText, useSaveCopy } from "../save";
import { LoadingModels, ModelPicker } from "./ModelPicker";
import { type Library, SourcePicker } from "./SourcePicker";
import { clock, minutesText, pickModel, stepProgress } from "./format";
import { useElapsed } from "./use-elapsed";
import { useVoiceModels } from "./use-voice-models";

export type LipSyncWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
  title?: string;
  lead?: string;
  /** inside another screen's panel: one narrow column and no recent, and what is made is handed over */
  panel?: boolean;
  onMade?: (id: string) => void;
};

/** Setting up the lip sync engine: a program environment of about 2 GB, fetched only on a click
 * after the size is shown. The model's own files (4.2 GB) are in the Model hub. */
function EngineCard({
  engine,
  api,
  onChanged,
}: {
  engine: LipSyncEngine;
  api: VoiceApi;
  onChanged: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // in the app window the model's own dialog sets the engine up with it (ADR-0086)
  const inDialog = useChoicesFor("faces") !== null;
  if (engine.installed) return null;
  const { plan, install } = engine;
  if (inDialog && plan.supported) return null;
  const working = install.state === "installing";
  async function go() {
    setAsking(false);
    setProblem(null);
    try {
      await api.installLipsyncEngine(plan.bytes);
      onChanged();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That did not work.");
    }
  }
  return (
    <section aria-label="Set up lip sync" className="grid gap-3 rounded-2xl border bg-card p-5">
      <h2 className="font-semibold text-lg">Set up lip sync on this computer</h2>
      {!plan.supported ? (
        <p className="text-muted-foreground">
          There is no lip sync engine for this kind of computer yet.
        </p>
      ) : (
        <>
          <p className="text-muted-foreground">
            Lip sync runs here, with no account and nothing sent away. It needs MuseTalk's program
            and its environment ({formatBytes(plan.bytes)}); the model's files are fetched in the
            Model hub afterwards. Setting up takes a few minutes.
          </p>
          {working ? (
            <div className="grid gap-2">
              <Bar
                value={install.total_bytes ? install.done_bytes / install.total_bytes : undefined}
              />
              <output className="text-muted-foreground text-sm">{install.message}</output>
            </div>
          ) : asking ? (
            <div className="flex flex-wrap items-center gap-2">
              <span>Download about {formatBytes(plan.bytes)} now?</span>
              <Button onClick={() => void go()}>Download</Button>
              <Button variant="ghost" onClick={() => setAsking(false)}>
                Not now
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button disabled={!plan.uv} onClick={() => setAsking(true)}>
                Set up lip sync ({formatBytes(plan.bytes)})
              </Button>
              {!plan.uv ? (
                <span className="text-muted-foreground text-sm">
                  The installer tool is missing: repair the app first.
                </span>
              ) : null}
            </div>
          )}
        </>
      )}
      {install.state === "failed" ? (
        <p role="alert" className="text-destructive text-sm">
          {install.message}
        </p>
      ) : null}
      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : null}
    </section>
  );
}

const STEPS = ["Picture", "Voice", "Make"];

/** The shapes a talking video can have; the picture is cropped to one, keeping its upper part. */
export const CLIP_SHAPES: { id: ClipShape; label: string; hint: string }[] = [
  { id: "picture", label: "As the picture", hint: "" },
  { id: "9:16", label: "Portrait", hint: "9:16" },
  { id: "16:9", label: "Landscape", hint: "16:9" },
  { id: "1:1", label: "Square", hint: "1:1" },
  { id: "4:5", label: "Social feed", hint: "4:5" },
];

/** where a crop is centred, across and down, as the engine does it (`CROP_CENTRE`) */
const CROP_POSITION = "50% 40%";

/** For a model that says the pixels its speed was measured at (`lipsync.speed_pixels`), the work grows
 * faster than the pixels (measured on a whole-picture model, `docs/spikes/lipsync-echomimic-v3-s1.md`).
 * MuseTalk redraws only the mouth, so it gives none and its speed is used as it is. */
const WORK_GROWTH = 1.8;

type CloudEstimate = { where: string; size: number; price?: number; work?: number };

/** "About 3 minutes on fal.ai and about $1.20 for 0:12 of video at 480p." Either part may be
 * unknown: a size not timed, or a price the provider does not list. */
export function cloudCost(c: CloudEstimate, voiceSeconds: number): string {
  const length = `${clock(voiceSeconds)} of video at ${c.size}p`;
  const dollars = c.price !== undefined ? `$${(c.price * voiceSeconds).toFixed(2)}` : null;
  if (c.work !== undefined) {
    const work = voiceSeconds * c.work; // Fabric makes a short clip in seconds, not minutes
    const time = work < 60 ? `${Math.max(5, Math.round(work / 5) * 5)} seconds` : minutesText(work);
    return `About ${time} on ${c.where}${dollars ? ` and about ${dollars}` : ""} for ${length}.`;
  }
  return dollars
    ? `About ${dollars} on ${c.where} for ${length}. Its time is not measured.`
    : `On ${c.where}. Its time and price for ${length} are not known here.`;
}

/**
 * Talking videos on the one make screen (ADR-0093, stage U6): a picture and a voice make a video of the face
 * saying it. The steps are in the ask column: the picture, then the voice; the stage shows the face before
 * anything is made, the progress while it is, and the video after.
 */
export function LipSyncWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
  title = "Lip sync",
  lead,
  panel = false,
  onMade,
}: LipSyncWorkspaceProps) {
  const { models, error, loading, reload } = useVoiceModels(api, "lipsync");
  const [engine, setEngine] = useState<LipSyncEngine | null>(null);
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [picture, setPicture] = useState<AddedPicture | null>(null);
  const [voiceFrom, setVoiceFrom] = useState<"words" | "recording">("words");
  const [words, setWords] = useState("");
  const [source, setSource] = useState<AudioSource | null>(null);
  const [shape, setShape] = useState<ClipShape>("picture");
  const [size, setSize] = useState<number | null>(null);
  const [library, setLibrary] = useState<Library>({ tracks: [], speeches: [] });
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [shownId, setShownId] = useState<string | null>(null);
  const [step, setStep] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<Clip | null>(null);
  const [deleting, setDeleting] = useState<Clip | null>(null);
  const abort = useRef<AbortController | null>(null);
  const pictureInput = useRef<HTMLInputElement>(null);
  const working = step !== null;
  const waited = useElapsed(working);

  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, "lipsync", modelId);
  const ready = chosen?.state === "ready";
  const sizes = chosen?.lipsync?.sizes ?? [];
  const sizeNow =
    size !== null && sizes.includes(size) ? size : (chosen?.lipsync?.default_size ?? null);
  // a cloud model that makes its own frame: a square one gets a square picture whatever was chosen,
  // and the size said is the one it made when measured, not this app's rule
  const ownFrame = chosen?.engine === "remote" ? chosen.lipsync?.frame : undefined;
  const squareOnly = ownFrame === "square";
  const shapeNow: ClipShape = squareOnly ? "1:1" : shape;
  const madeShort =
    ownFrame && sizeNow ? chosen?.lipsync?.frame_short?.[String(sizeNow)] : undefined;
  const frame = picture && sizeNow ? clipFrame(picture, shapeNow, sizeNow) : null;
  const madeFrame = picture && madeShort ? clipFrame(picture, shapeNow, madeShort) : null;
  const modelName = chosen?.title.split(" · ")[0] ?? "This model";
  const frameLine = !ownFrame
    ? frame
      ? `The video will be ${frame.width}×${frame.height} pixels.`
      : null
    : squareOnly
      ? madeShort
        ? `The video will be about ${madeShort}×${madeShort} pixels.`
        : "The video will be square."
      : madeFrame
        ? `The video will be about ${madeFrame.width}×${madeFrame.height} pixels; ${modelName} picks the exact size.`
        : `${modelName} picks the size, keeping this shape.`;
  const maxWords = 1000;

  const loadEngine = useCallback(
    () =>
      api
        .lipsyncEngine()
        .then(setEngine)
        .catch(() => undefined),
    [api],
  );
  const loadClips = useCallback(
    () =>
      api
        .clips()
        .then(setClips)
        .catch(() => setClips((c) => c ?? [])),
    [api],
  );
  useEffect(() => {
    void loadEngine();
    void loadClips();
    Promise.all([api.tracks({ limit: 200 }), api.speeches(200)])
      .then(([tracks, speeches]) => setLibrary({ tracks, speeches }))
      .catch(() => undefined);
  }, [api, loadEngine, loadClips]);
  useEffect(() => () => abort.current?.abort(), []);
  const installing = engine?.install.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const id = setInterval(() => {
      void loadEngine();
      void reload();
    }, 1000);
    return () => clearInterval(id);
  }, [installing, loadEngine, reload]);

  const voiceReady = voiceFrom === "words" ? words.trim().length >= 2 : source !== null;
  const pictureOk = picture !== null;
  const canMake = ready && pictureOk && voiceReady;
  const current = !pictureOk ? 0 : !voiceReady ? 1 : 2;

  async function addPicture(file: File) {
    setProblem(null);
    try {
      setPicture(await api.addPicture(file));
      setShownId(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That picture could not be added.");
    }
  }

  async function addRecording(file: File) {
    setProblem(null);
    try {
      const t = await api.importTrack(file);
      setLibrary((l) => ({ ...l, tracks: [t, ...l.tracks] }));
      setSource({ kind: "track", id: t.id });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That recording could not be added.");
    }
  }

  async function make() {
    if (!chosen || !picture || working) return;
    setProblem(null);
    setNote(null);
    setStep("Starting");
    abort.current = new AbortController();
    const signal = abort.current.signal;
    try {
      const r = await makeClip(
        runs,
        {
          picture: picture.id,
          model: chosen.id,
          shape: shapeNow,
          ...(sizeNow ? { size: sizeNow } : {}),
          ...(voiceFrom === "words" ? { text: words } : { source: source ?? undefined }),
        },
        signal,
        setStep,
      );
      if (r.ok) {
        const before = new Set((clips ?? []).map((c) => c.id));
        const list = await api.clips().catch(() => clips ?? []);
        setClips(list);
        const made = list.find((c) => !before.has(c.id))?.id ?? list[0]?.id ?? null;
        setShownId(made);
        if (made) onMade?.(made);
        setPicture(null);
      } else {
        setProblem(r.message);
      }
    } catch (e) {
      if (!signal.aborted) setProblem(e instanceof Error ? e.message : "That could not be made.");
    } finally {
      setStep(null);
      void reload();
    }
  }

  const saveCopy = useSaveCopy();
  async function save(c: Clip) {
    setProblem(null);
    try {
      const out = await saveCopy({
        name: fileNameFor(c.title, "mp4", "video"),
        blob: () => api.downloadClip(c.id),
      });
      if (out) setNote(savedText(out));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be saved.");
    }
  }

  async function rename(c: Clip, next: string) {
    setRenaming(null);
    try {
      const updated = await api.updateClip(c.id, { title: next });
      setClips((list) => (list ?? []).map((x) => (x.id === updated.id ? updated : x)));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be renamed.");
    }
  }

  async function remove(c: Clip) {
    setDeleting(null);
    try {
      await api.removeClip(c.id);
      setClips((list) => (list ?? []).filter((x) => x.id !== c.id));
      if (shownId === c.id) setShownId(null);
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
  if (loading || engine === null) return <LoadingModels />;

  const measuredAt = chosen?.lipsync?.speed_pixels;
  const speed =
    chosen?.measured.speed_x && frame && measuredAt
      ? chosen.measured.speed_x / ((frame.width * frame.height) / measuredAt) ** WORK_GROWTH
      : chosen?.measured.speed_x;
  const voiceSeconds =
    voiceFrom === "recording" && source
      ? source.kind === "track"
        ? library.tracks.find((t) => t.id === source.id)?.seconds
        : library.speeches.find((s) => s.id === source.id)?.seconds
      : Math.max(2, words.trim().split(/\s+/).length / 2.5);
  const shown = (clips ?? []).find((c) => c.id === shownId) ?? null;
  // a cloud model: what this voice costs and how long it should take there, so the person decides
  const cloud =
    chosen?.engine === "remote" && chosen.lipsync?.where && sizeNow
      ? {
          where: chosen.lipsync.where,
          size: sizeNow,
          price: chosen.lipsync.price_per_s?.[String(sizeNow)],
          work: chosen.lipsync.work_per_s?.[String(sizeNow)],
        }
      : null;

  const actions: Action[] = shown
    ? [
        { label: "Save MP4", onSelect: () => void save(shown), icon: <Save aria-hidden="true" /> },
        {
          label: "Rename",
          onSelect: () => setRenaming(shown),
          icon: <Pencil aria-hidden="true" />,
        },
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
        label: "Making the talking video…",
        text: `${step} · ${clock(waited)}`,
        value: stepProgress(step),
        onStop: () => abort.current?.abort(),
      }
    : problem && !shown && !picture
      ? { kind: "error", message: problem, onReset: () => setProblem(null) }
      : shown
        ? {
            kind: "result",
            children: (
              // biome-ignore lint/a11y/useMediaCaption: a talking video made from the person's own words or recording
              <video
                key={shown.id}
                controls
                playsInline
                preload="metadata"
                poster={shown.picture_url}
                src={shown.video_url}
                className="rounded-lg bg-black shadow-card"
              />
            ),
            caption: (
              <div className="grid gap-1">
                <span className="text-foreground">
                  {shown.title}{" "}
                  <span className="text-muted-foreground text-xs">
                    {clock(shown.seconds)} · {shown.width}×{shown.height}
                  </span>
                </span>
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
        : picture
          ? {
              kind: "result",
              children:
                shapeNow === "picture" || !frame ? (
                  <img
                    src={picture.url}
                    alt="The face to bring to life"
                    className="max-h-[calc(100dvh-24rem)] rounded-lg object-contain"
                  />
                ) : (
                  // what the video keeps of the picture: the same crop as the engine's
                  <img
                    src={picture.url}
                    alt="The face to bring to life, as the video will show it"
                    style={{
                      aspectRatio: `${frame.width} / ${frame.height}`,
                      objectPosition: CROP_POSITION,
                    }}
                    className="max-h-[calc(100dvh-24rem)] max-w-full rounded-lg object-cover"
                  />
                ),
              caption: problem ? (
                <p role="alert" className="m-0 text-destructive text-sm">
                  {problem}
                </p>
              ) : undefined,
            }
          : {
              kind: "empty",
              icon: UserRound,
              title: "The face appears here.",
              text: "Choose a picture of a face on the left, then give it words or a recording.",
            };

  const recent: RecentItem[] = (clips ?? []).slice(0, 24).map((c) => ({
    id: c.id,
    cover: c.picture_url ? (
      <img src={c.picture_url} alt="" className="size-full object-cover" />
    ) : (
      <Film className="size-5 text-muted-foreground" aria-hidden="true" />
    ),
    label: `Open: ${c.title}`,
    current: c.id === shownId,
    onOpen: () => {
      if (working) return;
      setProblem(null);
      setNote(null);
      setShownId(c.id);
    },
  }));

  return (
    <>
      <MakeScreen
        panel={panel}
        title={title}
        lead={
          // the page says "It runs on this computer"; a cloud model runs on its provider instead
          chosen?.engine === "remote" && lead
            ? lead.replace(
                / It runs on this computer\.$/,
                ` It runs on ${chosen.lipsync?.where ?? "the cloud"} with your key.`,
              )
            : lead
        }
        ask={
          <>
            {/* a model on the person's key needs nothing set up on this computer */}
            {chosen?.engine !== "remote" && (
              <EngineCard engine={engine} api={api} onChanged={loadEngine} />
            )}
            <ModelPicker
              models={models}
              task="lipsync"
              inBody={panel}
              value={chosen?.id ?? null}
              onChange={(id) => {
                setModelId(id);
                onModelChosen?.(id);
              }}
              onGetModel={onGetModel}
              disabled={working}
            />
            <Stepper steps={STEPS} current={current} />

            <section className="grid gap-3" aria-label="The picture">
              <h2 className="m-0 font-semibold text-ui-lg">The picture</h2>
              <input
                ref={pictureInput}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="sr-only"
                aria-label="Choose a picture"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) void addPicture(f);
                }}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="justify-self-start"
                disabled={working}
                onClick={() => pictureInput.current?.click()}
              >
                {picture ? "Choose another picture" : "Choose a picture"}
              </Button>
              <p className="m-0 text-muted-foreground text-xs">
                A front-facing face works best. Photos are cleaned of location and camera data.
              </p>
            </section>

            {squareOnly ? (
              <section className="grid gap-2" aria-label="Shape">
                <h2 className="m-0 font-semibold text-ui-lg">Shape</h2>
                <p className="m-0 text-muted-foreground text-xs">
                  {modelName} always makes a square video, so the picture is cut to a square,
                  keeping its upper part.
                </p>
              </section>
            ) : (
              <fieldset className="m-0 grid gap-2 border-0 p-0">
                <legend className="mb-1 font-semibold text-ui-lg">Shape</legend>
                <div className="flex flex-wrap gap-2">
                  {CLIP_SHAPES.map((s) => (
                    <Chip
                      key={s.id}
                      aria-pressed={shape === s.id}
                      disabled={working}
                      onClick={() => setShape(s.id)}
                    >
                      {s.label} {s.hint ? <span className="opacity-85">{s.hint}</span> : null}
                    </Chip>
                  ))}
                </div>
                <p className="m-0 text-muted-foreground text-xs">
                  Another shape crops the picture, keeping its upper part, where a face usually is.
                </p>
              </fieldset>
            )}

            {sizes.length > 1 ? (
              <fieldset className="m-0 grid gap-2 border-0 p-0">
                <legend className="mb-1 font-semibold text-ui-lg">Size</legend>
                <div className="flex flex-wrap gap-2">
                  {sizes.map((n) => (
                    <Chip
                      key={n}
                      aria-pressed={sizeNow === n}
                      disabled={working}
                      onClick={() => setSize(n)}
                    >
                      {n}p{" "}
                      <span className="opacity-85">
                        {n === sizes[0] ? "quicker" : n === sizes.at(-1) ? "sharper" : ""}
                      </span>
                    </Chip>
                  ))}
                </div>
                {frameLine ? (
                  <p className="m-0 text-muted-foreground text-xs">{frameLine}</p>
                ) : null}
              </fieldset>
            ) : ownFrame && frameLine && picture ? (
              <p className="m-0 text-muted-foreground text-xs">{frameLine}</p>
            ) : null}

            <section className="grid gap-3" aria-label="The voice">
              <h2 className="m-0 font-semibold text-ui-lg">The voice</h2>
              <Segmented
                label="Where the voice comes from"
                value={voiceFrom}
                onValueChange={(v) => setVoiceFrom(v as "words" | "recording")}
                options={[
                  { value: "words", label: "Words to say" },
                  { value: "recording", label: "A recording" },
                ]}
              />
              {voiceFrom === "words" ? (
                <div className="grid gap-2">
                  <Label htmlFor="lipsync-words">What should it say?</Label>
                  <Textarea
                    id="lipsync-words"
                    rows={3}
                    maxLength={maxWords}
                    value={words}
                    disabled={working}
                    placeholder="Good evening, and welcome."
                    onChange={(e) => setWords(e.target.value)}
                  />
                </div>
              ) : (
                <SourcePicker
                  id="lipsync-recording"
                  label="Which recording?"
                  library={library}
                  value={source}
                  disabled={working}
                  onAdd={(f) => void addRecording(f)}
                  onChange={setSource}
                />
              )}
            </section>
          </>
        }
        action={
          <>
            <Button
              type="button"
              size="lg"
              className="w-full rounded-full md:w-auto md:px-10"
              disabled={!canMake || working}
              onClick={() => void make()}
            >
              {working ? <Spinner /> : null}
              Make the video
            </Button>
            {!ready && chosen ? (
              <p className="mt-2 text-muted-foreground text-xs">
                Set lip sync up and get the model first (see above).
              </p>
            ) : cloud && voiceSeconds && !working ? (
              <p className="mt-2 text-muted-foreground text-xs">{cloudCost(cloud, voiceSeconds)}</p>
            ) : speed && voiceSeconds && !working ? (
              <p className="mt-2 text-muted-foreground text-xs">
                About {minutesText(voiceSeconds / speed)} of work on this computer for{" "}
                {clock(voiceSeconds)} of video.
              </p>
            ) : null}
          </>
        }
        stage={<Stage state={stage} className="w-full" />}
        recent={
          <RecentStrip
            title="Recent talking videos"
            items={recent}
            loading={clips === null}
            empty="Nothing made yet. Your first talking video will show up here."
          />
        }
      />
      {renaming ? (
        <NameDialog
          title="Name this video"
          label="Name"
          initial={renaming.title}
          onSubmit={(next) => void rename(renaming, next)}
          onCancel={() => setRenaming(null)}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title="Delete this video?"
          message={`“${deleting.title}” is deleted for good.`}
          onConfirm={() => void remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      ) : null}
    </>
  );
}
