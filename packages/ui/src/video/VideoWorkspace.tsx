"use client";

import {
  type RunClient,
  type VideoMode,
  type VideoResult,
  type VideoSummary,
  type VideosApi,
  clipLength,
} from "@wasifyai/client";
import { Film, Maximize2, Save } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { PromptField } from "../components/create";
import { EnhanceButton } from "../components/enhance-button";
import { MakeScreen } from "../components/make-screen";
import { Notice } from "../components/notice";
import { PictureInput } from "../components/picture-input";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Spinner } from "../components/spinner";
import { Stage, type StageState } from "../components/stage";
import { usePicture } from "../hooks/use-picture";
import { usePictureEvents } from "../hooks/use-picture-events";
import { VIDEO_PRODUCT, useVideoFlow } from "../hooks/use-video-flow";
import { extensionOf, fileNameFor, savedText, useSaveCopy } from "../save";
import { PageHeader } from "../window-bar";
import { appearsHere, makeLabel, makingLabel } from "../words";
import { ClipInput, EXTEND_LENGTHS } from "./ClipInput";
import { type LookChoice, Looks, type VideoLook, withWords } from "./Looks";

export const MAX_VIDEO_PROMPT = 500;

export const VIDEO_SHAPES = [
  { id: "landscape", label: "Landscape", hint: "3:2" },
  { id: "portrait", label: "Portrait", hint: "2:3" },
  { id: "square", label: "Square", hint: "1:1" },
] as const;

/** Clips are 5 or 8 seconds (owner, 2026-10-21): the engine decides what is too long, not this list. */
export const VIDEO_LENGTHS = [
  { seconds: 5, label: "5 seconds", note: "a few minutes" },
  { seconds: 8, label: "8 seconds", note: "takes about twice as long" },
] as const;

type PageMode = Exclude<VideoMode, "import">;

const EXAMPLES: Record<PageMode, string[]> = {
  text: [
    "A red fox walks through fresh snow at dawn, the camera slowly follows it",
    "Waves roll onto a quiet beach at sunset, seagulls drifting overhead",
    "A paper boat floats down a rain-soaked street, ripples spreading around it",
  ],
  image: [
    "Snow begins to fall softly and the camera slowly pushes in",
    "Clouds drift across the sky and the grass moves in the wind",
    "The light flickers gently and the camera slowly pans right",
  ],
  extend: [
    "The fox keeps walking through the snow",
    "The waves keep rolling onto the beach",
    "The camera keeps slowly moving forward",
  ],
};

/** What each screen calls itself. */
const COPY: Record<PageMode, { title: string; blurb: string; label: string; hint: string }> = {
  text: {
    title: "Make a video",
    blurb: "Describe a scene and get a short clip.",
    label: "What should the video show?",
    hint: "Describe the scene and how it moves.",
  },
  image: {
    title: "Animate a picture",
    blurb: "Choose a picture and say what should move.",
    label: "What should move?",
    hint: "Describe the picture and what moves in it. The clip keeps the shape of your picture.",
  },
  extend: {
    title: "Extend a video",
    blurb: "Carry one of your videos on for five or eight more seconds.",
    label: "What should keep happening?",
    hint: "The movement of the last second continues whatever you write, so a different action usually will not take.",
  },
};

/** What the screen hands the run: the picture is already uploaded (ADR-0039), so a run needs only its key. */
export type VideoFormValue = {
  mode: PageMode;
  prompt: string;
  shape: string;
  seconds: number;
  imageKey?: string;
  /** Extend video: the clip of the library to carry on */
  source?: VideoSummary;
};

/** A clip on the stage: the one just made, or one opened from the recent strip. */
type Shown = {
  videoId: string;
  videoUrl: string;
  posterUrl: string;
  prompt: string;
  mode: VideoMode;
  seconds: number;
  /** the record, when the clip came from the library (Extend this needs it) */
  summary?: VideoSummary;
};

const KIND: Record<VideoMode, string> = {
  text: "From words",
  image: "From a picture",
  extend: "Carried on",
  import: "Added from your computer",
};

const LAST_SECONDS_KEY = "wasifyai-video:last-seconds";

function lastSeconds(): number | null {
  try {
    const v = Number(localStorage.getItem(LAST_SECONDS_KEY));
    return v > 0 ? v : null;
  } catch {
    return null;
  }
}

function took(seconds: number): string {
  return seconds < 90 ? `${seconds} s` : `${Math.round(seconds / 60)} min`;
}

function jobText(job: { status: string; position?: number; progress?: number }): {
  text: string;
  value?: number;
} {
  if (job.status === "queued") {
    return {
      text: job.position && job.position > 1 ? `In line, place ${job.position}` : "You're next",
    };
  }
  if (job.status === "running") {
    const p = job.progress ?? 0;
    return { text: p > 0 ? `${Math.round(p * 100)}%` : "Starting", value: p };
  }
  return { text: "Getting ready" };
}

function shownOf(v: VideoSummary): Shown {
  return {
    videoId: v.id,
    videoUrl: v.video_url ?? "",
    posterUrl: v.poster_url ?? "",
    prompt: v.prompt,
    mode: v.mode,
    seconds: v.seconds,
    summary: v,
  };
}

export type VideoWorkspaceProps = {
  /** `text`: a description; `image`: a picture and what should move; `extend`: carry on one of your videos. */
  mode: PageMode;
  /** The app's client: starts the run, uploads the picture, enhances the prompt. Keep it the same object. */
  runs: RunClient;
  /** The recent strip, "Save a copy", and (Extend video) adding a file from this computer. */
  videos?: Pick<VideosApi, "exportCopy" | "list"> & Partial<Pick<VideosApi, "importVideo">>;
  /** Left of the top bar: the model button. */
  header?: ReactNode;
  /** In the ask column, above the fields: setup notices for this app (engine, model, memory). */
  notices?: ReactNode;
  /** When set, the fields are shown but making is refused with this reason. */
  blockedReason?: string | null;
  /** Asked before a clip is made; false stops it (the window opens its model picker when none is ready). */
  beforeMake?: () => boolean;
  /** Whether "Save a copy" is on offer. */
  canSave?: boolean;
  /** Where a finished clip can be downloaded from (the web app): "Download" is offered when given. */
  downloadHref?: (clip: { videoId: string }) => string;
  /** The line under the Make button: how long it takes here. */
  hint?: string;
  /** Called when the clip starts being made (the web app tells its tray). */
  onMaking?: () => void;
  /** "See all" on the recent strip. */
  onOpenLibrary?: () => void;
  /** Take a clip into Extend (the app opens the Extend screen with it chosen). */
  onExtendThis?: (video: VideoSummary) => void;
  /** Animate: a picture to start from ("Animate this" on a picture), fetched and handed over like one chosen. */
  sourceImage?: { url: string; name: string } | null;
  /** Extend: the clip to start from. */
  sourceVideo?: VideoSummary | null;
  /** The looks the person taught the video model: "My looks" is shown when there are any. */
  looks?: VideoLook[];
};

/**
 * Make a clip from words, from a picture, or by carrying one of the person's videos on, on the one make screen
 * (ADR-0093): the ask column, the clip playing on the stage, the recent clips under it. Shared by the web app
 * and the desktop window.
 */
export function VideoWorkspace({
  mode,
  runs,
  videos,
  header,
  notices,
  blockedReason = null,
  beforeMake,
  canSave = false,
  downloadHref,
  hint,
  onMaking,
  onOpenLibrary,
  onExtendThis,
  sourceImage = null,
  sourceVideo = null,
  looks = [],
}: VideoWorkspaceProps) {
  const id = useId();
  const flow = useVideoFlow(runs);
  const { state } = flow;
  const pic = usePicture(VIDEO_PRODUCT, runs);
  const [prompt, setPrompt] = useState(
    sourceVideo && sourceVideo.mode !== "import"
      ? sourceVideo.prompt.slice(0, MAX_VIDEO_PROMPT)
      : "",
  );
  const [edited, setEdited] = useState(false); // Extend: the person wrote their own words
  const [shape, setShape] = useState("landscape");
  const [seconds, setSeconds] = useState(5);
  const [source, setSource] = useState<VideoSummary | null>(sourceVideo);
  const [chosen, setChosen] = useState<LookChoice[]>([]);
  // a look that was taken away (its model removed) cannot stay chosen
  const usable = chosen.filter((c) => looks.some((l) => l.name === c.name));
  const [asked, setAsked] = useState<VideoFormValue | null>(null);
  const [picked, setPicked] = useState<VideoSummary | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [addProblem, setAddProblem] = useState<string | null>(null);
  const saveCopy = useSaveCopy();
  const startedAt = useRef<number | null>(null);
  const [lastTook, setLastTook] = useState<number | null>(lastSeconds);
  const { phase } = state;
  const working = phase === "checking" || phase === "making";

  // the recent strip: the last finished clips (Extend chooses from it)
  const [recent, setRecent] = useState<VideoSummary[] | null>(null);
  const [recentFailed, setRecentFailed] = useState(false);
  const loadRecent = useCallback(async () => {
    if (!videos) return;
    setRecentFailed(false);
    try {
      const page = await videos.list({ limit: 24, status: "done" });
      setRecent(page.videos.filter((v) => v.video_url));
    } catch {
      setRecentFailed(true);
    }
  }, [videos]);
  const resultId = phase === "done" ? state.result?.videoId : undefined;
  // biome-ignore lint/correctness/useExhaustiveDependencies: a finished clip is the trigger to read again
  useEffect(() => {
    void loadRecent();
  }, [loadRecent, resultId]);

  useEffect(() => {
    if (phase === "making") onMaking?.();
    if (phase === "done" && startedAt.current) {
      const s = Math.max(1, Math.round((Date.now() - startedAt.current) / 1000));
      startedAt.current = null;
      setLastTook(s);
      try {
        localStorage.setItem(LAST_SECONDS_KEY, String(s));
      } catch {
        // it is only a hint
      }
    }
  }, [phase, onMaking]);

  // a picture sent from Images ("Animate this") becomes the picture to animate, once
  const sourceKey = sourceImage?.url ?? "";
  // biome-ignore lint/correctness/useExhaustiveDependencies: the url is the trigger; `pic` is stable enough
  useEffect(() => {
    if (mode !== "image" || !sourceImage) return;
    let gone = false;
    fetch(sourceImage.url)
      .then((r) => r.blob())
      .then((blob) => {
        if (gone) return;
        void pic.choose(new File([blob], sourceImage.name, { type: blob.type || "image/png" }));
      })
      .catch(() => !gone && setProblem("That picture could not be opened here."));
    return () => {
      gone = true;
    };
  }, [sourceKey, mode]);

  function choose(clip: VideoSummary) {
    setSource(clip);
    // a clip made here has the words that made it; a file the person added only has its name
    if (!edited) setPrompt(clip.mode === "import" ? "" : clip.prompt.slice(0, MAX_VIDEO_PROMPT));
  }

  async function add(file: File) {
    if (!videos?.importVideo) return;
    setAdding(true);
    setAddProblem(null);
    try {
      const clip = await videos.importVideo(file);
      setRecent((old) => [clip, ...(old ?? []).filter((v) => v.id !== clip.id)]);
      choose(clip);
    } catch (err) {
      setAddProblem(
        err instanceof Error && err.message
          ? err.message
          : "That video could not be added. Try another file.",
      );
    } finally {
      setAdding(false);
    }
  }

  const { dragging } = usePictureEvents((file) => {
    if (mode === "image") void pic.choose(file);
    else if (mode === "extend") void add(file);
  }, mode !== "text");

  const trimmed = prompt.trim();
  const valid =
    trimmed.length > 0 &&
    prompt.length <= MAX_VIDEO_PROMPT &&
    (mode !== "image" || (pic.picture !== null && pic.status !== "uploading")) &&
    (mode !== "extend" || source !== null) &&
    !blockedReason;

  const begin = useCallback(
    (value: VideoFormValue) => {
      setAsked(value);
      setPicked(null);
      setSaved(null);
      setProblem(null);
      startedAt.current = Date.now();
      flow.start({
        mode: value.mode,
        prompt: withWords(value.prompt, looks, usable),
        loras: usable.length > 0 ? usable : undefined,
        shape: value.mode === "text" ? value.shape : undefined,
        seconds: value.seconds,
        imageKey: value.imageKey,
        sourceId: value.source?.id,
      });
    },
    [flow, looks, usable],
  );

  const make = useCallback(() => {
    if (!valid || working || !(beforeMake?.() ?? true)) return;
    if (mode === "image") pic.handOver(); // the run owns the picture from here
    begin({
      mode,
      prompt: trimmed,
      shape,
      seconds,
      imageKey: mode === "image" ? pic.picture?.key : undefined,
      source: mode === "extend" ? (source ?? undefined) : undefined,
    });
  }, [valid, working, beforeMake, mode, pic, begin, trimmed, shape, seconds, source]);

  const shown: Shown | null = picked
    ? shownOf(picked)
    : phase === "done" && state.result
      ? { ...(state.result as VideoResult) }
      : null;
  // the record of the clip just made, for Extend this: the strip has it once it is read again
  const shownSummary =
    shown?.summary ?? (shown ? recent?.find((v) => v.id === shown.videoId) : undefined);

  async function save(clip: Shown) {
    if (!videos) return;
    setProblem(null);
    setSaved(null);
    try {
      const done = await saveCopy({
        name: fileNameFor(clip.prompt, extensionOf(clip.videoUrl, "mp4"), "video"),
        copy: (path) => videos.exportCopy(clip.videoId, path),
      });
      if (done) setSaved(savedText(done));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The video could not be saved.");
    }
  }

  function extendThis(clip: VideoSummary) {
    if (mode === "extend") {
      setEdited(false);
      setSource(clip);
      setPrompt(clip.mode === "import" ? "" : clip.prompt.slice(0, MAX_VIDEO_PROMPT));
    } else onExtendThis?.(clip);
  }

  // what can be done with the clip on the stage: three buttons and a menu (ADR-0093 decision 8)
  const resultActions: Action[] = shown
    ? [
        ...(shownSummary && (mode === "extend" || onExtendThis)
          ? [
              {
                label: "Extend this",
                onSelect: () => extendThis(shownSummary),
                icon: <Maximize2 aria-hidden="true" />,
              },
            ]
          : []),
        ...(canSave && videos
          ? [
              {
                label: "Save a copy",
                onSelect: () => void save(shown),
                icon: <Save aria-hidden="true" />,
              },
            ]
          : []),
        ...(downloadHref
          ? [
              {
                label: "Download",
                href: downloadHref(shown),
                download: true,
                icon: <Save aria-hidden="true" />,
              },
            ]
          : []),
        ...(!picked && asked
          ? [{ label: "Make it again", onSelect: () => begin(asked), disabled: working }]
          : []),
        ...(shown.mode !== "import"
          ? [
              {
                label: "Use these words",
                onSelect: () => {
                  setPrompt(shown.prompt.slice(0, MAX_VIDEO_PROMPT));
                  setEdited(true);
                },
              },
            ]
          : []),
      ]
    : [];

  const job = jobText(state.job);
  const stageState: StageState = working
    ? {
        kind: "working",
        label: makingLabel("video"),
        text: [
          job.text,
          lastTook ? `the last one took ${took(lastTook)}` : null,
          "you can open another screen meanwhile",
        ]
          .filter(Boolean)
          .join(" · "),
        value: phase === "making" ? job.value : undefined,
        onStop: flow.reset,
      }
    : phase === "refused" && state.refusal
      ? {
          kind: "error",
          title: "We can't make that one",
          message: state.refusal.message,
          onReset: flow.reset,
        }
      : phase === "error" && state.error
        ? {
            kind: "error",
            message: state.error.message,
            onRetry: state.error.retryable ? flow.retry : undefined,
            onReset: flow.reset,
          }
        : shown
          ? {
              kind: "result",
              children: (
                // biome-ignore lint/a11y/useMediaCaption: made clips have no speech to caption
                <video
                  key={shown.videoUrl}
                  className="rounded-lg bg-black shadow-card"
                  controls
                  playsInline
                  preload="metadata"
                  poster={shown.posterUrl || undefined}
                  src={shown.videoUrl}
                />
              ),
              caption: (
                <div className="grid gap-2">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="min-w-0 truncate">{shown.prompt}</span>
                    <span className="shrink-0 text-xs">
                      {KIND[shown.mode]} · {clipLength(shown.seconds)}
                    </span>
                  </div>
                  {!picked ? <span className="text-xs">It is kept in Your videos.</span> : null}
                  {saved ? <output className="text-sm">{saved}</output> : null}
                  {problem ? (
                    <p className="m-0 text-destructive text-sm" role="alert">
                      {problem}
                    </p>
                  ) : null}
                </div>
              ),
              actions: resultActions,
            }
          : {
              kind: "empty",
              icon: Film,
              title: appearsHere("video"),
              text:
                mode === "extend"
                  ? "Choose a video and say what keeps happening, then press Make the video."
                  : mode === "image"
                    ? "Choose a picture and say what should move, then press Make the video."
                    : "Describe it on the left, then press Make the video.",
            };

  const recentItems: RecentItem[] = (recent ?? []).map((v) => ({
    id: v.id,
    cover: v.poster_url ? (
      <img src={v.poster_url} alt="" className="size-full object-cover" />
    ) : (
      <Film className="size-5 text-muted-foreground" aria-hidden="true" />
    ),
    label: mode === "extend" ? `Choose: ${v.prompt}` : `Open: ${v.prompt}`,
    current: mode === "extend" ? source?.id === v.id : picked?.id === v.id,
    onOpen: () => {
      if (working) return;
      flow.reset();
      setPicked(v);
      setSaved(null);
      if (mode === "extend") choose(v);
    },
  }));

  const lengths = mode === "extend" ? EXTEND_LENGTHS : VIDEO_LENGTHS;
  const keyboardHint = "Ctrl or ⌘ + Enter makes it too";

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* the model button, in the top bar (ADR-0093, stage U2) */}
      {header ? (
        <PageHeader className="flex h-14 shrink-0 items-center gap-4 border-b px-6 pt-1">
          <div className="flex min-w-0 items-center gap-2 ps-2 text-sm">{header}</div>
        </PageHeader>
      ) : null}
      <MakeScreen
        title={COPY[mode].title}
        lead={COPY[mode].blurb}
        ask={
          <>
            {notices}

            {mode === "image" ? (
              <PictureInput
                picture={pic.picture}
                status={pic.status}
                error={pic.error}
                dragging={dragging}
                onChoose={(f) => void pic.choose(f)}
                onRemove={pic.clear}
                onCancel={pic.cancel}
              />
            ) : null}

            {mode === "extend" ? (
              <>
                <ClipInput
                  source={source}
                  dragging={dragging}
                  adding={adding}
                  problem={addProblem}
                  canAdd={Boolean(videos?.importVideo)}
                  onAdd={(f) => void add(f)}
                  onClear={() => setSource(null)}
                />
                {recentFailed ? (
                  <Notice
                    tone="error"
                    title="Your videos could not be loaded"
                    actions={
                      <Button type="button" variant="outline" onClick={() => void loadRecent()}>
                        Try again
                      </Button>
                    }
                  >
                    Check that the app is running and try again.
                  </Notice>
                ) : null}
              </>
            ) : null}

            <PromptField
              id={id}
              label={COPY[mode].label}
              value={prompt}
              onChange={(v) => {
                setPrompt(v);
                setEdited(true);
              }}
              placeholder={EXAMPLES[mode][0] ?? ""}
              hintText={COPY[mode].hint}
              max={MAX_VIDEO_PROMPT}
              examples={EXAMPLES[mode]}
              exampleLabel={(ex) => ex.split(",")[0] ?? ex}
              enhance={
                mode === "extend" ? null : (
                  <EnhanceButton
                    enhance={runs.enhancePrompt}
                    product={VIDEO_PRODUCT}
                    kind={mode === "text" ? "text_to_video" : "image_to_video"}
                    value={prompt}
                    uploadId={pic.picture?.uploadId}
                    needsPicture={mode === "image"}
                    maxChars={MAX_VIDEO_PROMPT}
                    disabled={working || pic.status === "uploading"}
                    onChange={setPrompt}
                  />
                )
              }
              onSubmit={make}
            />

            <fieldset className="m-0 grid gap-2 border-0 p-0">
              <legend className="mb-1 font-semibold text-ui-lg">
                {mode === "extend" ? "How much to add" : "Length"}
              </legend>
              <div className="flex flex-wrap gap-2">
                {lengths.map((l) => (
                  <Chip
                    key={l.seconds}
                    aria-pressed={seconds === l.seconds}
                    onClick={() => setSeconds(l.seconds)}
                  >
                    {l.label} <span className="opacity-70">{l.note}</span>
                  </Chip>
                ))}
              </div>
              {mode === "extend" ? (
                <p className="m-0 text-muted-foreground text-xs">
                  The new video is kept beside the original. Its picture gets a little softer each
                  time a video is carried on, so two or three rounds is a sensible stop.
                </p>
              ) : null}
            </fieldset>

            {mode === "text" ? (
              <fieldset className="m-0 grid gap-2 border-0 p-0">
                <legend className="mb-1 font-semibold text-ui-lg">Shape</legend>
                <div className="flex flex-wrap gap-2">
                  {VIDEO_SHAPES.map((s) => (
                    <Chip key={s.id} aria-pressed={shape === s.id} onClick={() => setShape(s.id)}>
                      {s.label} <span className="opacity-70">{s.hint}</span>
                    </Chip>
                  ))}
                </div>
              </fieldset>
            ) : null}

            <Looks looks={looks} chosen={usable} onChange={setChosen} />
          </>
        }
        action={
          <>
            <Button
              type="button"
              size="lg"
              className="w-full rounded-full md:w-auto md:px-10"
              disabled={!valid || working}
              title={keyboardHint}
              aria-keyshortcuts="Control+Enter Meta+Enter"
              onClick={make}
            >
              {working ? <Spinner /> : null}
              {makeLabel("video")}
            </Button>
            {blockedReason ? (
              <p className="mt-2 text-destructive text-sm" role="alert">
                {blockedReason}
              </p>
            ) : (
              <p className="mt-2 text-muted-foreground text-xs">
                {hint ??
                  "A 5 second clip takes a few minutes on a fast Mac, and an 8 second one about twice as long."}
              </p>
            )}
            {problem && !shown ? (
              <p className="mt-2 text-destructive text-sm" role="alert">
                {problem}
              </p>
            ) : null}
          </>
        }
        stage={<Stage state={stageState} className="w-full" />}
        recent={
          videos ? (
            <RecentStrip
              title={mode === "extend" ? "Your videos: choose one to carry on" : "Recent videos"}
              items={recentItems}
              loading={recent === null && !recentFailed}
              onSeeAll={onOpenLibrary}
              empty={
                mode === "extend"
                  ? "You have no videos to carry on yet. Add one from your computer, or make one in Create."
                  : "Nothing made here yet. Your first video will show up here."
              }
            />
          ) : undefined
        }
      />
    </div>
  );
}
