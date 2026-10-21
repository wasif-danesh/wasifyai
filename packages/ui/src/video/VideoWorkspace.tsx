"use client";

import {
  type Mode,
  type RunClient,
  type VideoMode,
  type VideoResult,
  type VideoSummary,
  type VideosApi,
  clipLength,
} from "@wasifyai/client";
import { Library, Save } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { FailedNotice, JobMeter, PromptField, WorkingCard } from "../components/create";
import { EnhanceButton } from "../components/enhance-button";
import { Notice } from "../components/notice";
import { PictureInput } from "../components/picture-input";
import { type Picture, usePicture } from "../hooks/use-picture";
import { usePictureEvents } from "../hooks/use-picture-events";
import { VIDEO_PRODUCT, useVideoFlow } from "../hooks/use-video-flow";
import { extensionOf, fileNameFor, savedText, useSaveCopy } from "../save";
import { actions, chips, eyebrow, field, fieldLabel, panel } from "../styles";
import { ExtendForm } from "./ExtendForm";

export const MAX_VIDEO_PROMPT = 500;

export const VIDEO_SHAPES = [
  { id: "landscape", label: "Landscape", hint: "3:2" },
  { id: "portrait", label: "Portrait", hint: "2:3" },
  { id: "square", label: "Square", hint: "1:1" },
] as const;

/** Clips are 2 or 5 seconds; a longer one does not fit the time a job may take (ADR-0037). */
export const VIDEO_LENGTHS = [
  { seconds: 2, label: "2 seconds", note: "quick" },
  { seconds: 5, label: "5 seconds", note: "takes about four times as long" },
] as const;

const EXAMPLES: Record<Mode, string[]> = {
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
};

/** What the form hands over: the picture is already uploaded (ADR-0039), so a run needs only its key. */
export type VideoFormValue = {
  mode: VideoMode;
  prompt: string;
  shape: string;
  seconds: number;
  picture: Picture | null;
  /** Extend video: the clip of the library to carry on */
  source?: VideoSummary;
};

function VideoForm({
  mode,
  client,
  onSubmit,
  initial,
  hint,
}: {
  hint?: string;
  mode: Mode; // the form of text to video and image to video; Extend video has its own
  client: Pick<RunClient, "uploadImage" | "deleteUpload" | "enhancePrompt">;
  onSubmit: (value: VideoFormValue) => void;
  initial?: Partial<Pick<VideoFormValue, "prompt" | "shape" | "seconds">>;
}) {
  const id = useId();
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [shape, setShape] = useState(initial?.shape ?? "landscape");
  const [seconds, setSeconds] = useState<number>(initial?.seconds ?? 2);
  const pic = usePicture(VIDEO_PRODUCT, client);
  const { dragging } = usePictureEvents((file) => {
    if (mode === "image") void pic.choose(file);
  });

  const trimmed = prompt.trim();
  const valid =
    trimmed.length > 0 &&
    prompt.length <= MAX_VIDEO_PROMPT &&
    (mode === "text" || (pic.picture !== null && pic.status !== "uploading"));

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!valid) return;
    if (mode === "image") pic.handOver(); // the run owns the picture from here
    onSubmit({
      mode,
      prompt: trimmed,
      shape,
      seconds,
      picture: mode === "image" ? pic.picture : null,
    });
  }

  return (
    <form
      className={cn(
        panel,
        "gap-6 data-[dragging]:outline-2 data-[dragging]:outline-offset-4 data-[dragging]:outline-primary data-[dragging]:outline-dashed",
      )}
      onSubmit={submit}
      data-dragging={dragging || undefined}
    >
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

      <PromptField
        id={id}
        label={mode === "text" ? "What should the video show?" : "What should move?"}
        value={prompt}
        onChange={setPrompt}
        placeholder={EXAMPLES[mode][0] ?? ""}
        hintText={
          mode === "image"
            ? "Describe the picture and what moves in it. Press Ctrl or ⌘ + Enter to start."
            : "Describe the scene and how it moves. Press Ctrl or ⌘ + Enter to start."
        }
        max={MAX_VIDEO_PROMPT}
        examples={EXAMPLES[mode]}
        exampleLabel={(ex) => ex.split(",")[0] ?? ex}
        enhance={
          <EnhanceButton
            enhance={client.enhancePrompt}
            product={VIDEO_PRODUCT}
            kind={mode === "text" ? "text_to_video" : "image_to_video"}
            value={prompt}
            uploadId={pic.picture?.uploadId}
            needsPicture={mode === "image"}
            maxChars={MAX_VIDEO_PROMPT}
            disabled={pic.status === "uploading"}
            onChange={setPrompt}
          />
        }
        onSubmit={submit}
      />

      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>Length</legend>
        <div className={chips}>
          {VIDEO_LENGTHS.map((l) => (
            <Chip
              key={l.seconds}
              aria-pressed={seconds === l.seconds}
              onClick={() => setSeconds(l.seconds)}
            >
              {l.label} <span className="opacity-70">{l.note}</span>
            </Chip>
          ))}
        </div>
      </fieldset>

      {mode === "text" ? (
        <fieldset className={cn(field, "m-0 border-0 p-0")}>
          <legend className={cn(fieldLabel, "mb-1.5")}>Shape</legend>
          <div className={chips}>
            {VIDEO_SHAPES.map((s) => (
              <Chip key={s.id} aria-pressed={shape === s.id} onClick={() => setShape(s.id)}>
                {s.label} <span className="opacity-70">{s.hint}</span>
              </Chip>
            ))}
          </div>
        </fieldset>
      ) : null}

      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" size="lg" disabled={!valid}>
          Make my video
        </Button>
        <span className="text-muted-foreground">
          {mode === "image" ? "The clip keeps the shape of your picture. " : ""}
          {hint ?? "A 2 second clip takes about a minute on a fast Mac."}
        </span>
      </div>
    </form>
  );
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

export type VideoWorkspaceProps = {
  /** `text`: a description; `image`: a picture and what should move; `extend`: carry on one of your videos. */
  mode: Exclude<VideoMode, "import">;
  /** The app's client: starts the run, uploads the picture, enhances the prompt. Keep it the same object. */
  runs: RunClient;
  /** For "Save a copy" of a finished clip, and (Extend video) the list of clips to choose from. */
  videos?: Pick<VideosApi, "exportCopy" | "list"> & Partial<Pick<VideosApi, "importVideo">>;
  /** Above the form: setup notices for this app (engine, model, memory). */
  notices?: ReactNode;
  /** When set, the form is shown but making is refused with this reason. */
  blockedReason?: string | null;
  /** Whether "Save a copy" is on offer. */
  canSave?: boolean;
  /** Where a finished clip can be downloaded from (the web app): "Download" is offered when given. */
  downloadHref?: (result: VideoResult) => string;
  /** The line next to the Make button: how long it takes here. */
  hint?: string;
  /** Called when the clip starts being made (the web app tells its header). */
  onMaking?: () => void;
  onOpenLibrary?: () => void;
};

/** Make a clip from words or from a picture, watch it being made, and see the result. */
export function VideoWorkspace({
  mode,
  runs,
  videos,
  notices,
  blockedReason = null,
  canSave = false,
  downloadHref,
  hint,
  onMaking,
  onOpenLibrary,
}: VideoWorkspaceProps) {
  const { state, start, reset, retry } = useVideoFlow(runs);
  // What the person asked for, kept so a refusal or an error can bring it back for editing.
  const [asked, setAsked] = useState<VideoFormValue | undefined>();
  const [saved, setSaved] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const saveCopy = useSaveCopy();
  const { phase } = state;
  const working = phase === "checking" || phase === "making";

  const submit = (value: VideoFormValue) => {
    setAsked(value);
    setSaved(null);
    setProblem(null);
    start({
      mode: value.mode,
      prompt: value.prompt,
      shape: value.shape,
      seconds: value.seconds,
      imageKey: value.picture?.key,
      sourceId: value.source?.id,
    });
  };

  async function save(result: VideoResult) {
    if (!videos) return;
    setProblem(null);
    try {
      const done = await saveCopy({
        name: fileNameFor(result.prompt, extensionOf(result.videoUrl, "mp4"), "video"),
        copy: (path) => videos.exportCopy(result.videoId, path),
      });
      if (done) setSaved(savedText(done));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The video could not be saved.");
    }
  }

  useEffect(() => {
    if (phase === "making") onMaking?.();
  }, [phase, onMaking]);

  const job = jobText(state.job);
  const showForm = phase === "idle" || phase === "refused";
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-5">
      <div className="sr-only" aria-live="polite">
        {state.label}
      </div>
      {notices}

      {showForm ? (
        <>
          {phase === "refused" && state.refusal ? (
            <Notice tone="warn" title="We can't make that one">
              {state.refusal.message}
            </Notice>
          ) : null}
          {blockedReason ? (
            <Notice tone="warn" title="This model will not run here">
              {blockedReason}
            </Notice>
          ) : null}
          {mode === "extend" ? (
            videos ? (
              <ExtendForm
                videos={videos}
                onSubmit={({ source, prompt }) =>
                  blockedReason
                    ? null
                    : submit({
                        mode: "extend",
                        prompt,
                        shape: "landscape",
                        seconds: 2,
                        picture: null,
                        source,
                      })
                }
                initial={asked?.source ? { source: asked.source, prompt: asked.prompt } : undefined}
                hint={hint}
              />
            ) : null
          ) : (
            <VideoForm
              mode={mode}
              client={runs}
              onSubmit={(v) => (blockedReason ? null : submit(v))}
              initial={asked}
              hint={hint}
            />
          )}
        </>
      ) : (
        <>
          {asked ? (
            <section className={panel} aria-label="Your request">
              <span className={eyebrow}>
                {asked.mode === "extend"
                  ? "Your video, carried on"
                  : `${asked.mode === "image" ? "Your picture, brought to life" : "Your scene"} · ${clipLength(asked.seconds)}`}
              </span>
              <p>{asked.prompt}</p>
            </section>
          ) : null}

          {working ? (
            <WorkingCard label={state.label || "Working"} onCancel={reset}>
              {phase === "making" ? (
                <>
                  <JobMeter
                    title="Making your video"
                    text={job.text}
                    value={job.value}
                    label="Video progress"
                  />
                  <p className="text-muted-foreground text-sm">
                    You can open another screen: the clip carries on and will be in Your videos.
                  </p>
                </>
              ) : null}
            </WorkingCard>
          ) : null}

          {phase === "done" && state.result ? (
            <>
              <Notice tone="ok" title="Your video is ready">
                It's saved in Your videos, where you can watch and save it any time.
              </Notice>
              <figure className={cn(panel, "m-0 justify-items-center")}>
                {/* biome-ignore lint/a11y/useMediaCaption: generated clips have no speech to caption */}
                <video
                  className="h-auto max-h-[60vh] max-w-full rounded-xl bg-black shadow-card"
                  controls
                  playsInline
                  preload="metadata"
                  poster={state.result.posterUrl || undefined}
                  src={state.result.videoUrl}
                />
              </figure>
              <div className={actions}>
                {canSave && videos ? (
                  <Button type="button" onClick={() => void save(state.result as VideoResult)}>
                    <Save className="size-4" /> Save a copy
                  </Button>
                ) : null}
                {downloadHref ? (
                  <Button asChild>
                    <a href={downloadHref(state.result)} download>
                      <Save className="size-4" /> Download
                    </a>
                  </Button>
                ) : null}
                <Button type="button" variant="outline" onClick={reset}>
                  Make another
                </Button>
                {onOpenLibrary ? (
                  <Button type="button" variant="outline" onClick={onOpenLibrary}>
                    <Library className="size-4" /> Your videos
                  </Button>
                ) : null}
              </div>
              {saved ? <output className="text-sm">{saved}</output> : null}
              {problem ? (
                <Notice tone="error" title="That did not work">
                  {problem}
                </Notice>
              ) : null}
            </>
          ) : null}

          {phase === "error" && state.error ? (
            <FailedNotice
              message={state.error.message}
              retryable={state.error.retryable}
              onRetry={retry}
              onReset={reset}
            />
          ) : null}
        </>
      )}
    </div>
  );
}
