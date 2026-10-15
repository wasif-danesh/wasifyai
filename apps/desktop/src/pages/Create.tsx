// SPDX-License-Identifier: AGPL-3.0-only
import type { ImageResult } from "@wasifyai/client";
import {
  Button,
  Chip,
  EnhanceButton,
  FailedNotice,
  IMAGE_PRODUCT,
  JobMeter,
  MAX_PROMPT,
  Notice,
  PictureInput,
  PromptField,
  SIZES,
  Spinner,
  cn,
  useImageFlow,
  usePicture,
  usePictureEvents,
} from "@wasifyai/ui";
import { ImageIcon, Info, Library } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";
import { client, modelsApi } from "../api";
import { COMFYUI, type ComponentStatus, componentStatus, onComponentStatus } from "../engine";
import { type ImageSummary, listImages, sizeName, when } from "../images";
import type { ModelEntry } from "../models";
import type { Route } from "../router";

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

/** Something shown in the preview: a result just made, or an earlier image picked from the strip. */
type Shown = {
  id: string;
  url: string;
  prompt: string;
  mode: "text" | "image";
  width: number;
  height: number;
  when?: string;
};

function fromResult(r: ImageResult): Shown {
  return {
    id: r.imageId,
    url: r.imageUrl,
    prompt: r.prompt,
    mode: r.mode,
    width: r.width,
    height: r.height,
  };
}

function fromSummary(s: ImageSummary): Shown {
  return {
    id: s.id,
    url: s.image_url,
    prompt: s.prompt,
    mode: s.mode,
    width: s.width,
    height: s.height,
    when: when(s.created_at),
  };
}

function useRecent(refreshOn: string | undefined) {
  const [images, setImages] = useState<ImageSummary[]>([]);
  // `refreshOn` is the id of the newest result: a new one means the strip should be read again
  // biome-ignore lint/correctness/useExhaustiveDependencies: refreshOn is the trigger
  useEffect(() => {
    let gone = false;
    listImages(14)
      .then((p) => !gone && setImages(p.images))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [refreshOn]);
  return images;
}

function useModel(): ModelEntry | null {
  const [model, setModel] = useState<ModelEntry | null>(null);
  useEffect(() => {
    let gone = false;
    modelsApi
      .overview()
      .then((o) => !gone && setModel(o.models[0] ?? null))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, []);
  return model;
}

function useImageEngine(): ComponentStatus | null {
  const [status, setStatus] = useState<ComponentStatus | null>(null);
  useEffect(() => {
    let stop: (() => void) | undefined;
    let gone = false;
    componentStatus(COMFYUI)
      .then((s) => !gone && setStatus(s))
      .catch(() => {});
    onComponentStatus((id, s) => id === COMFYUI && !gone && setStatus(s)).then((off) => {
      stop = off;
      if (gone) off();
    });
    return () => {
      gone = true;
      stop?.();
    };
  }, []);
  return status;
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

/** Create and Edit: the controls on the left, the picture on the right, recent images underneath. */
export function CreatePage({ mode, go }: { mode: "text" | "image"; go: (r: Route) => void }) {
  const id = useId();
  const flow = useImageFlow(client);
  const pic = usePicture(IMAGE_PRODUCT, client);
  const [prompt, setPrompt] = useState("");
  const [size, setSize] = useState<string>("square");
  const [picked, setPicked] = useState<Shown | null>(null);
  const [recipeOpen, setRecipeOpen] = useState(false);
  const model = useModel();
  const engine = useImageEngine();
  const { dragging } = usePictureEvents((file) => {
    if (mode === "image") void pic.choose(file);
  }, mode === "image");

  const { state } = flow;
  const working = state.phase === "checking" || state.phase === "working";
  const recent = useRecent(state.result?.imageId);

  const trimmed = prompt.trim();
  const valid =
    trimmed.length > 0 &&
    prompt.length <= MAX_PROMPT &&
    (mode === "text" || (pic.picture !== null && pic.status !== "uploading"));

  const generate = useCallback(() => {
    if (!valid || working) return;
    setPicked(null);
    setRecipeOpen(false);
    if (mode === "image") pic.handOver(); // the run owns the picture from here
    flow.start({
      mode,
      prompt: trimmed,
      size: mode === "text" ? size : undefined,
      imageKey: mode === "image" ? pic.picture?.key : undefined,
    });
  }, [valid, working, mode, pic, flow, trimmed, size]);

  const shown: Shown | null =
    picked ?? (state.phase === "done" && state.result ? fromResult(state.result) : null);
  const job = jobText(state.job);
  const placeholderEngine = engine?.state === "not_installed";

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* top bar */}
      <header
        data-tauri-drag-region
        className="flex h-14 shrink-0 items-center justify-between gap-4 border-b px-6 pt-1"
      >
        <div className="flex items-center gap-2 ps-2 text-sm">
          <span className="font-medium">{model?.title ?? "Image model"}</span>
          {model ? (
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-xs",
                model.status === "ready" ? "text-ok" : "text-muted-foreground",
              )}
            >
              {model.status === "ready" ? "ready" : "not downloaded"}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-1 text-sm">
          <span className="rounded-full bg-accent px-3 py-1.5 font-medium">
            {mode === "text" ? "Create" : "Edit"}
          </span>
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-muted-foreground hover:bg-accent"
            onClick={() => go("library")}
          >
            <Library className="size-4" /> Library
          </button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(19rem,28rem)_minmax(0,1fr)]">
        {/* controls */}
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
              {placeholderEngine ? (
                <Notice tone="info" title="Placeholder pictures">
                  Real images need the image engine set up once.{" "}
                  <button
                    type="button"
                    className="underline underline-offset-4"
                    onClick={() => go("settings")}
                  >
                    Open Settings
                  </button>
                  .
                </Notice>
              ) : null}
              {model && model.status !== "ready" && engine?.state === "installed" ? (
                <Notice tone="warn" title="The model is not on this computer yet">
                  Get it in{" "}
                  <button
                    type="button"
                    className="underline underline-offset-4"
                    onClick={() => go("models")}
                  >
                    Models
                  </button>{" "}
                  before making real images.
                </Notice>
              ) : null}

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
                    enhance={client.enhancePrompt}
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
            </div>
          </div>
          <div className="shrink-0 border-t px-6 py-4">
            <div>
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
          </div>
        </section>

        {/* picture and the recent strip */}
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
                  className="max-h-[calc(100dvh-24rem)] max-w-full rounded-xl object-contain shadow-card"
                  src={shown.url}
                  alt={shown.prompt}
                  width={shown.width || undefined}
                  height={shown.height || undefined}
                />
                <figcaption className="sr-only">Your image is ready</figcaption>
                <div className="flex flex-wrap items-center gap-2">
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
                {recipeOpen ? (
                  <dl className="grid max-w-xl grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border p-4 text-sm">
                    <dt className="text-muted-foreground">Prompt</dt>
                    <dd>{shown.prompt}</dd>
                    <dt className="text-muted-foreground">Kind</dt>
                    <dd>{shown.mode === "image" ? "Edit of a picture" : "From text"}</dd>
                    <dt className="text-muted-foreground">Size</dt>
                    <dd>
                      {shown.width}×{shown.height} ({sizeName(shown.width, shown.height)})
                    </dd>
                    {shown.when ? (
                      <>
                        <dt className="text-muted-foreground">Made</dt>
                        <dd>{shown.when}</dd>
                      </>
                    ) : null}
                  </dl>
                ) : null}
                <p className="text-muted-foreground text-xs">It's saved on this computer.</p>
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
                        setPicked(fromSummary(img));
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
