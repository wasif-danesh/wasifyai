"use client";

import {
  type ImageSummary,
  type ImagesApi,
  type RunClient,
  canRunAgain,
  sizeName,
  when,
} from "@wasifyai/client";
import { Heart, ImageIcon, Info, Library, RotateCw, Save } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { FailedNotice, JobMeter, PromptField } from "../components/create";
import { EnhanceButton } from "../components/enhance-button";
import { Notice } from "../components/notice";
import { PictureInput } from "../components/picture-input";
import { Spinner } from "../components/spinner";
import { IMAGE_PRODUCT, useImageFlow } from "../hooks/use-image-flow";
import { usePicture } from "../hooks/use-picture";
import { usePictureEvents } from "../hooks/use-picture-events";
import { MAX_PROMPT, SIZES } from "./ImageForm";

const EXAMPLES = {
  text: [
    "A lighthouse on a cliff at sunrise, soft watercolour",
    "A cosy reading nook with a sleeping cat, warm light",
    "A paper-craft city at night, glowing windows",
  ],
  image: [
    "Make it look like a watercolour painting",
    "Change the background to a snowy forest",
    "Turn the daytime scene into a golden-hour evening",
  ],
} as const;

/** A recipe loaded into the form: what "make it again" starts from. */
export type StudioPreset = { prompt: string; size: string | null; seed: number };

export function presetOf(image: ImageSummary): StudioPreset | null {
  const r = image.recipe;
  if (!canRunAgain(image) || r === null) return null;
  return { prompt: r.prompt, size: r.size, seed: r.seed };
}

export type ImageStudioProps = {
  mode: "text" | "image";
  /** The client the screen talks to the engine with (packages/client). */
  runs: RunClient;
  images: ImagesApi;
  /** Left of the top bar: the model, for example. */
  header?: ReactNode;
  /** Above the form: setup notices for this app. */
  notices?: ReactNode;
  /** Load this recipe into the form once (see `presetOf`). */
  preset?: StudioPreset | null;
  /** Show the library: the top bar offers it when given. */
  onOpenLibrary?: () => void;
  /** Whether "Save a copy" (the engine exports to a folder) is on offer. */
  canSave?: boolean;
};

function useRecent(refreshOn: string | undefined, api: ImagesApi) {
  const [recent, setRecent] = useState<ImageSummary[]>([]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: refreshOn is the trigger
  useEffect(() => {
    let gone = false;
    api
      .list({ limit: 14 })
      .then((p) => !gone && setRecent(p.images))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [refreshOn, api]);
  return [recent, setRecent] as const;
}

function jobText(job: { status: string; position?: number; progress?: number }) {
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

/**
 * Create and Edit in two panels: the controls on the left, the picture, its recipe and the recent
 * images on the right. Shared by the web app and the desktop window.
 */
export function ImageStudio({
  mode,
  runs,
  images,
  header,
  notices,
  preset,
  onOpenLibrary,
  canSave = false,
}: ImageStudioProps) {
  const id = useId();
  const flow = useImageFlow(runs);
  const pic = usePicture(IMAGE_PRODUCT, runs);
  const [prompt, setPrompt] = useState(preset?.prompt ?? "");
  const [size, setSize] = useState<string>(preset?.size ?? "square");
  const [seed, setSeed] = useState<number | null>(preset?.seed ?? null);
  const [picked, setPicked] = useState<ImageSummary | null>(null);
  const [made, setMade] = useState<ImageSummary | null>(null);
  const [recipeOpen, setRecipeOpen] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const { dragging } = usePictureEvents((file) => {
    if (mode === "image") void pic.choose(file);
  }, mode === "image");

  const { state } = flow;
  const working = state.phase === "checking" || state.phase === "working";
  const [recent, setRecent] = useRecent(state.result?.imageId, images);

  // the full record of what was just made: its recipe and favourite flag
  const resultId = state.phase === "done" ? state.result?.imageId : undefined;
  useEffect(() => {
    if (!resultId) {
      setMade(null);
      return;
    }
    let gone = false;
    images
      .get(resultId)
      .then((i) => !gone && setMade(i))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [resultId, images]);

  const trimmed = prompt.trim();
  const valid =
    trimmed.length > 0 &&
    prompt.length <= MAX_PROMPT &&
    (mode === "text" || (pic.picture !== null && pic.status !== "uploading"));

  const begin = useCallback(
    (text: string, sizeId: string, withSeed: number | null) => {
      setPicked(null);
      setRecipeOpen(false);
      setSaved(null);
      setProblem(null);
      if (mode === "image") pic.handOver(); // the run owns the picture from here
      flow.start({
        mode,
        prompt: text,
        size: mode === "text" ? sizeId : undefined,
        imageKey: mode === "image" ? pic.picture?.key : undefined,
        seed: mode === "text" && withSeed !== null ? withSeed : undefined,
      });
    },
    [mode, pic, flow],
  );

  const generate = useCallback(() => {
    if (valid && !working) begin(trimmed, size, seed);
  }, [valid, working, begin, trimmed, size, seed]);

  const shown: ImageSummary | null =
    picked ??
    made ??
    (state.phase === "done" && state.result
      ? {
          id: state.result.imageId,
          prompt: state.result.prompt,
          mode: state.result.mode,
          width: state.result.width,
          height: state.result.height,
          created_at: new Date().toISOString(),
          image_url: state.result.imageUrl,
          thumb_url: state.result.imageUrl,
          recipe: null,
          favourite: false,
        }
      : null);

  function again(image: ImageSummary) {
    const p = presetOf(image);
    if (!p || working) return;
    setPrompt(p.prompt);
    setSize(p.size ?? "square");
    setSeed(p.seed);
    begin(p.prompt, p.size ?? "square", p.seed);
  }

  async function toggleFavourite(image: ImageSummary) {
    setProblem(null);
    try {
      const next = await images.setFavourite(image.id, !image.favourite);
      setRecent((list) => list.map((i) => (i.id === next.id ? next : i)));
      if (picked?.id === next.id) setPicked(next);
      if (made?.id === next.id) setMade(next);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That did not work.");
    }
  }

  async function save(image: ImageSummary) {
    setProblem(null);
    setSaved(null);
    try {
      const out = await images.exportCopy(image.id);
      setSaved(`Saved as ${out.name} in Downloads.`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The image could not be saved.");
    }
  }

  const job = jobText(state.job);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header
        data-tauri-drag-region
        className="flex h-14 shrink-0 items-center justify-between gap-4 border-b px-6 pt-1"
      >
        <div className="flex items-center gap-2 ps-2 text-sm">{header}</div>
        <div className="flex items-center gap-1 text-sm">
          <span className="rounded-full bg-accent px-3 py-1.5 font-medium">
            {mode === "text" ? "Create" : "Edit"}
          </span>
          {onOpenLibrary ? (
            <button
              type="button"
              className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-muted-foreground hover:bg-accent"
              onClick={onOpenLibrary}
            >
              <Library className="size-4" /> Library
            </button>
          ) : null}
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(19rem,28rem)_minmax(0,1fr)]">
        <section className="flex min-h-0 flex-col border-e" aria-label="Controls">
          <div className="min-h-0 flex-1 overflow-auto px-6 py-6">
            <h1 className="font-semibold text-2xl tracking-tight">
              {mode === "text" ? "Create images" : "Edit a picture"}
            </h1>
            <p className="mt-1 text-muted-foreground text-sm">
              {mode === "text"
                ? "Generate a new image from a prompt."
                : "Choose a picture and say what to change."}
            </p>

            <div className="mt-6 grid gap-5">
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

              <PromptField
                id={id}
                label={mode === "text" ? "Prompt" : "What should change?"}
                value={prompt}
                onChange={setPrompt}
                placeholder={EXAMPLES[mode][0]}
                hintText="Press Ctrl or ⌘ + Enter to generate."
                max={MAX_PROMPT}
                examples={[...EXAMPLES[mode]]}
                exampleLabel={(ex) => ex.split(",")[0] ?? ex}
                enhance={
                  <EnhanceButton
                    enhance={runs.enhancePrompt}
                    product={IMAGE_PRODUCT}
                    kind={mode === "text" ? "text_to_image" : "edit_image"}
                    value={prompt}
                    uploadId={pic.picture?.uploadId}
                    needsPicture={mode === "image"}
                    maxChars={MAX_PROMPT}
                    disabled={working || pic.status === "uploading"}
                    onChange={setPrompt}
                  />
                }
                onSubmit={generate}
              />

              {mode === "text" ? (
                <fieldset className="m-0 grid gap-2 border-0 p-0">
                  <legend className="mb-1 font-semibold text-[0.95rem]">Aspect ratio</legend>
                  <div className="flex flex-wrap gap-2">
                    {SIZES.map((s) => (
                      <Chip key={s.id} aria-pressed={size === s.id} onClick={() => setSize(s.id)}>
                        {s.label} <span className="opacity-70">{s.hint}</span>
                      </Chip>
                    ))}
                  </div>
                </fieldset>
              ) : (
                <p className="text-muted-foreground text-sm">
                  The result keeps the size of your picture.
                </p>
              )}

              {mode === "text" && seed !== null ? (
                <p className="flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm">
                  <span>
                    Using seed <span className="font-mono">{seed}</span> from an earlier image.
                  </span>
                  <button
                    type="button"
                    className="text-muted-foreground underline underline-offset-4"
                    onClick={() => setSeed(null)}
                  >
                    Use a new one
                  </button>
                </p>
              ) : null}
            </div>
          </div>
          <div className="shrink-0 border-t px-6 py-4">
            <Button
              type="button"
              size="lg"
              className="rounded-full px-10"
              disabled={!valid || working}
              onClick={generate}
            >
              {working ? <Spinner /> : null}
              Generate
            </Button>
          </div>
        </section>

        <section className="flex min-h-0 min-w-0 flex-col" aria-label="Result">
          <div className="grid min-h-0 flex-1 place-items-center overflow-auto p-6">
            {working ? (
              <output className="grid w-full max-w-md gap-4">
                <div className="flex items-center gap-3 font-semibold">
                  <Spinner />
                  <span>{state.label || "Working"}</span>
                </div>
                {state.phase === "working" ? (
                  <JobMeter
                    title="Painting your image"
                    text={job.text}
                    value={job.value}
                    label="Image progress"
                  />
                ) : null}
                <div>
                  <Button type="button" variant="outline" onClick={flow.reset}>
                    Cancel
                  </Button>
                </div>
              </output>
            ) : state.phase === "refused" && state.refusal ? (
              <div className="w-full max-w-md">
                <Notice tone="warn" title="We can't make that one">
                  {state.refusal.message}
                </Notice>
              </div>
            ) : state.phase === "error" && state.error ? (
              <div className="w-full max-w-md">
                <FailedNotice
                  message={state.error.message}
                  retryable={state.error.retryable}
                  onRetry={flow.retry}
                  onReset={flow.reset}
                />
              </div>
            ) : shown ? (
              <figure className="m-0 grid max-w-full justify-items-center gap-4">
                <img
                  className="max-h-[calc(100dvh-26rem)] max-w-full rounded-xl object-contain shadow-card"
                  src={shown.image_url}
                  alt={shown.prompt}
                  width={shown.width || undefined}
                  height={shown.height || undefined}
                />
                <figcaption className="sr-only">Your image is ready</figcaption>
                <div className="flex flex-wrap items-center justify-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    aria-pressed={shown.favourite}
                    onClick={() => void toggleFavourite(shown)}
                  >
                    <Heart className={cn("size-4", shown.favourite && "fill-current")} />
                    {shown.favourite ? "Favourite" : "Add to favourites"}
                  </Button>
                  {canSave ? (
                    <Button type="button" variant="outline" onClick={() => void save(shown)}>
                      <Save className="size-4" /> Save a copy
                    </Button>
                  ) : null}
                  {canRunAgain(shown) ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={working}
                      onClick={() => again(shown)}
                    >
                      <RotateCw className="size-4" /> Make it again
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    variant="outline"
                    aria-expanded={recipeOpen}
                    onClick={() => setRecipeOpen((v) => !v)}
                  >
                    <Info className="size-4" /> Recipe
                  </Button>
                  <Button type="button" variant="outline" onClick={() => setPrompt(shown.prompt)}>
                    Use this prompt
                  </Button>
                </div>
                {recipeOpen ? <RecipeList image={shown} /> : null}
                {saved ? <output className="text-sm">{saved}</output> : null}
                {problem ? (
                  <p className="text-destructive text-sm" role="alert">
                    {problem}
                  </p>
                ) : null}
              </figure>
            ) : (
              <div className="grid justify-items-center gap-3 text-center text-muted-foreground">
                <ImageIcon className="size-12 opacity-40" aria-hidden="true" />
                <p>Your image appears here.</p>
              </div>
            )}
          </div>

          {recent.length > 0 ? (
            <div className="shrink-0 border-t px-6 py-3">
              <ul className="flex gap-3 overflow-x-auto" aria-label="Recent images">
                {recent.map((img) => (
                  <li key={img.id} className="shrink-0">
                    <button
                      type="button"
                      aria-label={`Open: ${img.prompt}`}
                      aria-pressed={picked?.id === img.id}
                      className={cn(
                        "overflow-hidden rounded-lg border-2 border-transparent outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        picked?.id === img.id && "border-primary",
                      )}
                      onClick={() => {
                        flow.reset();
                        setPicked(img);
                      }}
                    >
                      <img src={img.thumb_url} alt="" className="size-20 object-cover" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

/** What made an image, as a small list. Older images have no seed: they show what the row kept. */
export function RecipeList({ image }: { image: ImageSummary }) {
  const r = image.recipe;
  return (
    <dl className="grid max-w-xl grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border p-4 text-sm">
      <dt className="text-muted-foreground">Prompt</dt>
      <dd>{image.prompt}</dd>
      <dt className="text-muted-foreground">Kind</dt>
      <dd>{image.mode === "image" ? "Edit of a picture" : "From text"}</dd>
      <dt className="text-muted-foreground">Size</dt>
      <dd>
        {image.width}×{image.height} ({sizeName(image.width, image.height)})
      </dd>
      {r ? (
        <>
          <dt className="text-muted-foreground">Seed</dt>
          <dd className="font-mono">{r.seed}</dd>
        </>
      ) : null}
      <dt className="text-muted-foreground">Made</dt>
      <dd>{when(image.created_at)}</dd>
    </dl>
  );
}
