"use client";

import {
  HttpError,
  type ImageMode,
  type ImageSummary,
  type ImagesApi,
  type LoraChoice,
  type RunClient,
  canRunAgain,
  sizeName,
  when,
} from "@wasifyai/client";
import { Heart, ImageIcon, Info, Library, Pencil, RotateCw, Save, Shuffle } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
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
import { extensionOf, fileNameFor, savedText, useSaveCopy } from "../save";
import { PageHeader } from "../window-bar";
import { MAX_PROMPT, SIZES } from "./ImageForm";
import { MaskPainter, type MaskPainterHandle } from "./MaskPainter";

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
  reference: [
    "The cat from picture 1 sitting on the chair from picture 2, in a sunlit room",
    "The person from picture 1 wearing the jacket from picture 2, on a city street at night",
    "The sneaker from picture 1 on a wooden table next to the plant from picture 2",
  ],
  inpaint: [
    "A white coffee cup with steam",
    "A plush red velvet cushion",
    "A small green plant in a clay pot",
  ],
} as const;

/** What each screen calls itself. */
const COPY: Record<ImageMode, { tab: string; title: string; blurb: string; label: string }> = {
  text: {
    tab: "Create",
    title: "Create images",
    blurb: "Generate a new image from a prompt.",
    label: "Prompt",
  },
  image: {
    tab: "Edit",
    title: "Edit a picture",
    blurb: "Choose a picture and say what to change.",
    label: "What should change?",
  },
  reference: {
    tab: "Reference",
    title: "Make a picture from two pictures",
    blurb: "Choose two pictures and say what to take from each.",
    label: "What should the new picture show?",
  },
  inpaint: {
    tab: "Inpaint",
    title: "Change part of a picture",
    blurb: "Paint the area to change and say what to put there.",
    label: "What should go in the painted area?",
  },
};

/** A recipe loaded into the form: what "make it again" starts from. */
export type WorkspacePreset = {
  prompt: string;
  size: string | null;
  seed: number;
  loras: LoraChoice[];
};

/** A style the image engine can apply (or could, with one click). */
export type LoraOption = { id?: string; name: string; title: string; size?: number };

const MAX_STYLES = 3;

export function presetOf(image: ImageSummary): WorkspacePreset | null {
  const r = image.recipe;
  if (!canRunAgain(image) || r === null) return null;
  return { prompt: r.prompt, size: r.size, seed: r.seed, loras: r.loras ?? [] };
}

export type ImageWorkspaceProps = {
  mode: ImageMode;
  /** The client the screen talks to the engine with (packages/client). */
  runs: RunClient;
  images: ImagesApi;
  /** Left of the top bar: the model, for example. */
  header?: ReactNode;
  /** Above the form: setup notices for this app. */
  notices?: ReactNode;
  /** Load this recipe into the form once (see `presetOf`). */
  preset?: WorkspacePreset | null;
  /** Show the library: the top bar offers it when given. */
  onOpenLibrary?: () => void;
  /** Whether "Save a copy" (the engine exports to a folder) is on offer. */
  canSave?: boolean;
  /** Where an image can be downloaded from (the web app): "Download" is offered when given. */
  downloadHref?: (image: ImageSummary) => string;
  /** Why making an image is not possible right now (for example: the model cannot fit). */
  blockedReason?: string | null;
  /** Asked before an image is made; false stops it (the window opens its model picker when none is ready). */
  beforeMake?: () => boolean;
  /** Styles (LoRAs) the image engine can apply now. */
  loras?: LoraOption[];
  /** Styles one click away (their folder is not read yet), with `onUseLora` to do it. */
  availableLoras?: LoraOption[];
  onUseLora?: (id: string) => Promise<void> | void;
  /** Take a result into Edit as its source picture (the app opens the Edit screen). */
  onEditThis?: (image: ImageSummary) => void;
  /** A picture to start Edit from: fetched and handed over like one the person chose. */
  sourceImage?: { url: string; name: string } | null;
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
export function ImageWorkspace({
  mode,
  runs,
  images,
  header,
  notices,
  preset,
  onOpenLibrary,
  canSave = false,
  downloadHref,
  blockedReason = null,
  beforeMake,
  loras = [],
  availableLoras = [],
  onUseLora,
  onEditThis,
  sourceImage = null,
}: ImageWorkspaceProps) {
  const id = useId();
  const flow = useImageFlow(runs);
  const pic = usePicture(IMAGE_PRODUCT, runs);
  const pic2 = usePicture(IMAGE_PRODUCT, runs); // the second reference (Reference only)
  const painter = useRef<MaskPainterHandle>(null);
  const [painted, setPainted] = useState(0); // the share of the picture that is painted (Inpaint)
  const [sending, setSending] = useState(false); // the painted area is being uploaded
  const [prompt, setPrompt] = useState(preset?.prompt ?? "");
  const [size, setSize] = useState<string>(preset?.size ?? "square");
  const [seed, setSeed] = useState<number | null>(preset?.seed ?? null);
  const [styles, setStyles] = useState<LoraChoice[]>(preset?.loras ?? []);
  const [stylesOpen, setStylesOpen] = useState((preset?.loras ?? []).length > 0);
  const [picked, setPicked] = useState<ImageSummary | null>(null);
  const [made, setMade] = useState<ImageSummary | null>(null);
  const [recipeOpen, setRecipeOpen] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const saveCopy = useSaveCopy();
  const [problem, setProblem] = useState<string | null>(null);
  const { dragging } = usePictureEvents((file) => {
    // a dropped or pasted picture goes to the first free place
    if (mode === "reference" && pic.picture !== null && pic2.picture === null)
      void pic2.choose(file);
    else void pic.choose(file);
  }, mode !== "text");

  const { state } = flow;
  const working = state.phase === "checking" || state.phase === "working" || sending;
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
      // a record already held for this picture is newer than one read before it was changed
      // (the heart pressed while this was on its way)
      .then((i) => !gone && setMade((held) => (held?.id === i.id ? held : i)))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [resultId, images]);

  const trimmed = prompt.trim();
  const valid =
    trimmed.length > 0 &&
    prompt.length <= MAX_PROMPT &&
    (mode === "text" || (pic.picture !== null && pic.status !== "uploading")) &&
    (mode !== "reference" || (pic2.picture !== null && pic2.status !== "uploading")) &&
    (mode !== "inpaint" || painted > 0) &&
    !blockedReason;

  // an image sent from another screen ("Edit this result") becomes the Edit source, once
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
      .catch(() => !gone && setProblem("That picture could not be opened for editing."));
    return () => {
      gone = true;
    };
  }, [sourceKey, mode]);

  const begin = useCallback(
    async (text: string, sizeId: string, withSeed: number | null, withStyles: LoraChoice[]) => {
      setPicked(null);
      setRecipeOpen(false);
      setSaved(null);
      setProblem(null);
      let maskKey: string | undefined;
      if (mode === "inpaint") {
        // the painted area goes up now, as it is at this moment, like a picture the person chose
        setSending(true);
        try {
          const file = await painter.current?.exportMask();
          if (!file) {
            setProblem("Paint the part of the picture you want to change.");
            return;
          }
          maskKey = (await runs.uploadImage(IMAGE_PRODUCT, file)).key;
        } catch (e) {
          setProblem(
            e instanceof HttpError
              ? e.message
              : "We couldn't send the painted area. Check your connection and try again.",
          );
          return;
        } finally {
          setSending(false);
        }
      }
      if (mode !== "text") pic.handOver(); // the run owns the pictures from here
      if (mode === "reference") pic2.handOver();
      flow.start({
        mode,
        prompt: text,
        size: mode === "text" || mode === "reference" ? sizeId : undefined,
        imageKey: mode !== "text" ? pic.picture?.key : undefined,
        image2Key: mode === "reference" ? pic2.picture?.key : undefined,
        maskKey,
        seed: mode === "text" && withSeed !== null ? withSeed : undefined,
        loras: withStyles.length > 0 ? withStyles : undefined,
      });
    },
    [mode, pic, pic2, flow, runs],
  );

  const generate = useCallback(() => {
    if (valid && !working && (beforeMake?.() ?? true)) void begin(trimmed, size, seed, styles);
  }, [valid, working, begin, trimmed, size, seed, styles, beforeMake]);

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
    setStyles(p.loras);
    void begin(p.prompt, p.size ?? "square", p.seed, p.loras);
  }

  /** The same recipe with a new seed: another picture in the same spirit. */
  function vary(image: ImageSummary) {
    const p = presetOf(image);
    if (!p || working) return;
    setPrompt(p.prompt);
    setSize(p.size ?? "square");
    setSeed(null);
    setStyles(p.loras);
    void begin(p.prompt, p.size ?? "square", null, p.loras);
  }

  function toggleStyle(name: string) {
    setStyles((cur) =>
      cur.some((s) => s.name === name)
        ? cur.filter((s) => s.name !== name)
        : cur.length >= MAX_STYLES
          ? cur
          : [...cur, { name, weight: 1 }],
    );
  }

  function setStrength(name: string, weight: number) {
    setStyles((cur) => cur.map((s) => (s.name === name ? { ...s, weight } : s)));
  }

  async function toggleFavourite(image: ImageSummary) {
    setProblem(null);
    try {
      const next = await images.setFavourite(image.id, !image.favourite);
      setRecent((list) => list.map((i) => (i.id === next.id ? next : i)));
      if (picked?.id === next.id) setPicked(next);
      if (made?.id === next.id || resultId === next.id) setMade(next);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That did not work.");
    }
  }

  async function save(image: ImageSummary) {
    setProblem(null);
    setSaved(null);
    try {
      const out = await saveCopy({
        name: fileNameFor(image.prompt, extensionOf(image.image_url, "png"), "image"),
        copy: (path) => images.exportCopy(image.id, path),
      });
      if (out) setSaved(savedText(out));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The image could not be saved.");
    }
  }

  const job = jobText(state.job);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader className="flex h-14 shrink-0 items-center justify-between gap-4 border-b px-6 pt-1">
        <div className="flex min-w-0 items-center gap-2 ps-2 text-sm">{header}</div>
        <div className="flex shrink-0 items-center gap-1 text-sm">
          <span className="rounded-full bg-accent px-3 py-1.5 font-medium">{COPY[mode].tab}</span>
          {onOpenLibrary ? (
            <button
              type="button"
              className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-muted-foreground hover:bg-accent"
              onClick={onOpenLibrary}
            >
              <Library className="size-4" /> <span className="max-sm:sr-only">Library</span>
            </button>
          ) : null}
        </div>
      </PageHeader>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-auto md:grid-cols-[minmax(19rem,28rem)_minmax(0,1fr)] md:overflow-visible">
        <section
          className="flex flex-col border-b md:min-h-0 md:border-e md:border-b-0"
          aria-label="Controls"
        >
          <div className="flex-1 px-6 py-6 md:min-h-0 md:overflow-auto">
            <h1 className="font-semibold text-2xl tracking-tight">{COPY[mode].title}</h1>
            <p className="mt-1 text-muted-foreground text-sm">{COPY[mode].blurb}</p>

            <div className="mt-6 grid gap-5">
              {notices}

              {mode !== "text" ? (
                <PictureInput
                  label={mode === "reference" ? "Picture 1" : "Your picture"}
                  preview={mode !== "inpaint"}
                  picture={pic.picture}
                  status={pic.status}
                  error={pic.error}
                  dragging={dragging}
                  onChoose={(f) => void pic.choose(f)}
                  onRemove={pic.clear}
                  onCancel={pic.cancel}
                />
              ) : null}

              {mode === "reference" ? (
                <>
                  <PictureInput
                    label="Picture 2"
                    picture={pic2.picture}
                    status={pic2.status}
                    error={pic2.error}
                    dragging={dragging && pic.picture !== null && pic2.picture === null}
                    onChoose={(f) => void pic2.choose(f)}
                    onRemove={pic2.clear}
                    onCancel={pic2.cancel}
                  />
                  <p className="text-muted-foreground text-sm">
                    Call them “picture 1” and “picture 2” in your words. It takes about a minute.
                  </p>
                </>
              ) : null}

              {mode === "inpaint" && pic.picture ? (
                <MaskPainter
                  picture={pic.picture}
                  disabled={working}
                  onCoverage={setPainted}
                  handleRef={painter}
                />
              ) : null}

              <PromptField
                id={id}
                label={COPY[mode].label}
                value={prompt}
                onChange={setPrompt}
                placeholder={EXAMPLES[mode][0]}
                hintText="Press Ctrl or ⌘ + Enter to generate."
                max={MAX_PROMPT}
                examples={[...EXAMPLES[mode]]}
                exampleLabel={(ex) => ex.split(",")[0] ?? ex}
                enhance={
                  mode === "text" || mode === "image" ? (
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
                  ) : undefined
                }
                onSubmit={generate}
              />

              {mode === "text" || mode === "reference" ? (
                <fieldset className="m-0 grid gap-2 border-0 p-0">
                  <legend className="mb-1 font-semibold text-ui-lg">Aspect ratio</legend>
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
                  {mode === "inpaint"
                    ? "Only the painted area changes; the rest stays as it is. A larger area works better than a small one."
                    : "The result keeps the size of your picture."}
                </p>
              )}

              {loras.length > 0 || availableLoras.length > 0 || styles.length > 0 ? (
                <section className="grid gap-2" aria-label="Styles">
                  <button
                    type="button"
                    className="flex items-center justify-between font-semibold text-ui-lg"
                    aria-expanded={stylesOpen}
                    onClick={() => setStylesOpen((v) => !v)}
                  >
                    <span>
                      Styles{" "}
                      <span className="font-normal text-muted-foreground">
                        {styles.length ? `(${styles.length} chosen)` : "(optional)"}
                      </span>
                    </span>
                    <span aria-hidden="true">{stylesOpen ? "−" : "+"}</span>
                  </button>
                  {stylesOpen ? (
                    <div className="grid gap-2">
                      <p className="text-muted-foreground text-xs">
                        A style (LoRA) changes the look. Use ones made for FLUX.2 klein 4B; others
                        give noise. Up to {MAX_STYLES}.
                      </p>
                      {loras.map((l) => {
                        const on = styles.find((s) => s.name === l.name);
                        return (
                          <div key={l.name} className="grid gap-1 rounded-md border px-3 py-2">
                            <label className="flex items-center gap-2 text-sm">
                              <input
                                type="checkbox"
                                checked={Boolean(on)}
                                disabled={!on && styles.length >= MAX_STYLES}
                                onChange={() => toggleStyle(l.name)}
                              />
                              <span className="min-w-0 flex-1 truncate" title={l.name}>
                                {l.title}
                              </span>
                            </label>
                            {on ? (
                              <label className="flex items-center gap-2 text-muted-foreground text-xs">
                                Strength
                                <input
                                  type="range"
                                  min={0.1}
                                  max={2}
                                  step={0.05}
                                  value={on.weight}
                                  aria-label={`Strength of ${l.title}`}
                                  className="flex-1"
                                  onChange={(e) => setStrength(l.name, Number(e.target.value))}
                                />
                                <span className="w-9 text-end tabular-nums">
                                  {on.weight.toFixed(2)}
                                </span>
                              </label>
                            ) : null}
                          </div>
                        );
                      })}
                      {styles
                        .filter((s) => !loras.some((l) => l.name === s.name))
                        .map((s) => (
                          <p key={s.name} className="rounded-md border px-3 py-2 text-sm">
                            {s.name}{" "}
                            <span className="text-muted-foreground">is not available here</span>{" "}
                            <button
                              type="button"
                              className="underline underline-offset-4"
                              onClick={() => toggleStyle(s.name)}
                            >
                              Take it out
                            </button>
                          </p>
                        ))}
                      {availableLoras.map((l) => (
                        <div
                          key={l.id ?? l.name}
                          className="flex items-center gap-2 rounded-md border border-dashed px-3 py-2 text-sm"
                        >
                          <span
                            className="min-w-0 flex-1 truncate text-muted-foreground"
                            title={l.name}
                          >
                            {l.title}
                          </span>
                          {onUseLora && l.id ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => void onUseLora(l.id as string)}
                            >
                              Use it
                            </Button>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}

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
            {blockedReason ? (
              <p className="mt-2 text-destructive text-sm" role="alert">
                {blockedReason}
              </p>
            ) : null}
            {problem && !shown ? (
              <p className="mt-2 text-destructive text-sm" role="alert">
                {problem}
              </p>
            ) : null}
          </div>
        </section>

        <section className="flex min-h-[22rem] min-w-0 flex-col md:min-h-0" aria-label="Result">
          <div className="grid flex-1 place-items-center p-6 md:min-h-0 md:overflow-auto">
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
                  {downloadHref && shown.id ? (
                    <Button asChild variant="outline">
                      <a href={downloadHref(shown)} download>
                        <Save className="size-4" /> Download
                      </a>
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
                  {canRunAgain(shown) ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={working}
                      onClick={() => vary(shown)}
                    >
                      <Shuffle className="size-4" /> Vary
                    </Button>
                  ) : null}
                  {onEditThis ? (
                    <Button type="button" variant="outline" onClick={() => onEditThis(shown)}>
                      <Pencil className="size-4" /> Edit this result
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

const KINDS: Record<ImageMode, string> = {
  text: "From text",
  image: "Edit of a picture",
  reference: "Made from two pictures",
  inpaint: "Change of a painted area",
};

/** What made an image, as a small list. Older images have no seed: they show what the row kept. */
export function RecipeList({ image }: { image: ImageSummary }) {
  const r = image.recipe;
  return (
    <dl className="grid max-w-xl grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border p-4 text-sm">
      <dt className="text-muted-foreground">Prompt</dt>
      <dd>{image.prompt}</dd>
      <dt className="text-muted-foreground">Kind</dt>
      <dd>{KINDS[image.mode]}</dd>
      <dt className="text-muted-foreground">Size</dt>
      <dd>
        {image.width}×{image.height} ({sizeName(image.width, image.height)})
      </dd>
      {r ? (
        <>
          <dt className="text-muted-foreground">Seed</dt>
          <dd className="font-mono">{r.seed}</dd>
          {r.loras && r.loras.length > 0 ? (
            <>
              <dt className="text-muted-foreground">Styles</dt>
              <dd>{r.loras.map((l) => `${l.name} (${l.weight})`).join(", ")}</dd>
            </>
          ) : null}
        </>
      ) : null}
      <dt className="text-muted-foreground">Made</dt>
      <dd>{when(image.created_at)}</dd>
    </dl>
  );
}
