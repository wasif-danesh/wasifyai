"use client";

import {
  HttpError,
  type ImageMode,
  type ImageSummary,
  type ImagesApi,
  type LoraChoice,
  type RunClient,
  type StyleChoice,
  type StylesApi,
  canRunAgain,
  sizeName,
  when,
} from "@wasifyai/client";
import { Film, Heart, ImageIcon, Pencil, Save } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { Chip } from "../components/chip";
import { PromptField } from "../components/create";
import { EnhanceButton } from "../components/enhance-button";
import { Experts } from "../components/experts";
import { MakeScreen } from "../components/make-screen";
import { PictureInput } from "../components/picture-input";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Slider } from "../components/slider";
import { Spinner } from "../components/spinner";
import { Stage, type StageState } from "../components/stage";
import { takeDraft } from "../draft";
import { IMAGE_PRODUCT, useImageFlow } from "../hooks/use-image-flow";
import { usePicture } from "../hooks/use-picture";
import { usePictureEvents } from "../hooks/use-picture-events";
import { extensionOf, fileNameFor, savedText, useSaveCopy } from "../save";
import { PageHeader } from "../window-bar";
import { appearsHere, makeLabel, makingLabel } from "../words";
import { MAX_PROMPT, SIZES } from "./ImageForm";
import { MaskPainter, type MaskPainterHandle } from "./MaskPainter";
import { StylesSection } from "./style-picker/StylesSection";

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
    title: "Make a picture",
    blurb: "Describe it in any language.",
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
  /** null: a new picture each time (a style sent from Train, for example) */
  seed: number | null;
  loras: LoraChoice[];
  /** the desktop's styles by id (ADR-0091) */
  styles?: StyleChoice[];
  /** Advanced: sampling steps, and a size of one's own */
  steps?: number | null;
  own?: { width: number; height: number } | null;
};

const MAX_PICTURES = 4;

/** A style the image engine can apply (or could, with one click). */
export type LoraOption = { id?: string; name: string; title: string; size?: number };

const MAX_STYLES = 8; // ADR-0091 decision 7
const LAST_SECONDS_KEY = "wasifyai-image:last-seconds";

function lastSeconds(): number | null {
  try {
    const v = Number(localStorage.getItem(LAST_SECONDS_KEY));
    return v > 0 ? v : null;
  } catch {
    return null;
  }
}

export function presetOf(image: ImageSummary): WorkspacePreset | null {
  const r = image.recipe;
  if (!canRunAgain(image) || r === null) return null;
  return {
    prompt: r.prompt,
    size: r.size,
    seed: r.seed,
    loras: r.loras ?? [],
    styles: r.styles ?? [],
    steps: r.steps ?? null,
    own: r.own_size ? { width: r.width, height: r.height } : null,
  };
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
  /** The desktop's styles (ADR-0091): given, the Styles section is always shown and chooses by id. */
  stylesApi?: StylesApi;
  /** "Look in a folder…" in the Add menu: where the folders of other apps are set */
  onOpenFolders?: () => void;
  /** the web (ADR-0091 S5): `stylesApi` lists the styles an admin added; a person only chooses */
  stylesReadOnly?: boolean;
  /** Take a result into Edit as its source picture (the app opens the Edit screen). */
  onEditThis?: (image: ImageSummary) => void;
  /** Take a result into Video's Animate as its picture (the app opens the Animate screen). */
  onAnimateThis?: (image: ImageSummary) => void;
  /** A picture to start Edit from: fetched and handed over like one the person chose. */
  sourceImage?: { url: string; name: string; id?: string } | null;
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
  canSave = false,
  downloadHref,
  blockedReason = null,
  beforeMake,
  loras = [],
  availableLoras = [],
  onUseLora,
  stylesApi,
  onOpenFolders,
  stylesReadOnly = false,
  onEditThis,
  onAnimateThis,
  onOpenLibrary,
  sourceImage = null,
}: ImageWorkspaceProps) {
  const id = useId();
  const flow = useImageFlow(runs);
  const pic = usePicture(IMAGE_PRODUCT, runs);
  const pic2 = usePicture(IMAGE_PRODUCT, runs); // the second reference (Reference only)
  // the picture of the library the first picture is, when it was handed over from there ("Edit this")
  const fromLibrary = useRef<string | null>(null);
  const painter = useRef<MaskPainterHandle>(null);
  const [painted, setPainted] = useState(0); // the share of the picture that is painted (Inpaint)
  const [sending, setSending] = useState(false); // the painted area is being uploaded
  // a recipe sent here, or the words typed in the chat box before a quick start (ADR-0093 U9)
  const [prompt, setPrompt] = useState(() => preset?.prompt ?? takeDraft());
  const [size, setSize] = useState<string>(preset?.size ?? "square");
  const [seed, setSeed] = useState<number | null>(preset?.seed ?? null);
  const [styles, setStyles] = useState<LoraChoice[]>(preset?.loras ?? []);
  const [chosen, setChosen] = useState<StyleChoice[]>(preset?.styles ?? []);
  // Advanced (ADR-0091 decision 10): steps (null: the model's own), a size of one's own, how many pictures
  const [steps, setSteps] = useState<number | null>(preset?.steps ?? null);
  const [own, setOwn] = useState<{ width: number; height: number } | null>(preset?.own ?? null);
  const [count, setCount] = useState(1);
  // the pictures still to make after this one, and the seed of the last (consecutive seeds)
  const more = useRef<{ left: number; seed: number | null } | null>(null);
  const startedAt = useRef<number | null>(null);
  const [took, setTook] = useState<number | null>(lastSeconds);
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
    else {
      fromLibrary.current = null; // a file of their own: not the library's picture any more
      void pic.choose(file);
    }
  }, mode !== "text");

  const { state } = flow;
  const working = state.phase === "checking" || state.phase === "working" || sending;
  const [recent, setRecent] = useRecent(state.result?.imageId, images);
  // how long the last picture took, said while the next one is made
  useEffect(() => {
    if (state.phase === "done" && startedAt.current) {
      const seconds = Math.max(1, Math.round((Date.now() - startedAt.current) / 1000));
      startedAt.current = null;
      setTook(seconds);
      try {
        localStorage.setItem(LAST_SECONDS_KEY, String(seconds));
      } catch {
        // it is only a hint
      }
    }
  }, [state.phase]);

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
        // the picture of the library it came from, kept with what is made from it (ADR-0093, U8)
        fromLibrary.current = sourceImage.id ?? null;
        void pic.choose(new File([blob], sourceImage.name, { type: blob.type || "image/png" }));
      })
      .catch(() => !gone && setProblem("That picture could not be opened for editing."));
    return () => {
      gone = true;
    };
  }, [sourceKey, mode]);

  const begin = useCallback(
    async (
      text: string,
      sizeId: string,
      withSeed: number | null,
      withStyles: LoraChoice[],
      withChosen: StyleChoice[],
      withSteps: number | null = steps,
      withOwn: { width: number; height: number } | null = own,
    ) => {
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
      startedAt.current = Date.now();
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
        styles:
          stylesApi && withChosen.length > 0
            ? withChosen.map((c) => ({ id: c.id, strength: c.strength }))
            : undefined,
        steps: withSteps ?? undefined,
        width: withOwn?.width,
        height: withOwn?.height,
        sourceId: mode !== "text" ? (fromLibrary.current ?? undefined) : undefined,
      });
    },
    [mode, pic, pic2, flow, runs, stylesApi, steps, own],
  );

  const generate = useCallback(() => {
    if (!valid || working || !(beforeMake?.() ?? true)) return;
    // several pictures: consecutive seeds from this one (a new one when none is set; text to image)
    const first =
      count > 1 && mode === "text" ? (seed ?? Math.floor(Math.random() * 2 ** 31)) : seed;
    more.current = count > 1 ? { left: count - 1, seed: mode === "text" ? first : null } : null;
    void begin(trimmed, size, first, styles, chosen);
  }, [valid, working, begin, trimmed, size, seed, styles, chosen, beforeMake, count, mode]);

  // the next of several pictures, once one is done (each finished picture has its own id)
  // biome-ignore lint/correctness/useExhaustiveDependencies: the phase and the finished picture are the trigger
  useEffect(() => {
    const next = more.current;
    if (state.phase === "error" || state.phase === "refused") more.current = null;
    if (state.phase !== "done" || !next || next.left <= 0) return;
    const seedNext = next.seed === null ? null : (next.seed + 1) % 2 ** 31;
    more.current = next.left > 1 ? { left: next.left - 1, seed: seedNext } : null;
    void begin(trimmed, size, seedNext, styles, chosen);
  }, [state.phase, resultId]);

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
    setChosen(p.styles ?? []);
    setSteps(p.steps ?? null);
    setOwn(p.own ?? null);
    void begin(p.prompt, p.size ?? "square", p.seed, p.loras, p.styles ?? [], p.steps, p.own);
  }

  /** The same recipe with a new seed: another picture in the same spirit. */
  function vary(image: ImageSummary) {
    const p = presetOf(image);
    if (!p || working) return;
    setPrompt(p.prompt);
    setSize(p.size ?? "square");
    setSeed(null);
    setStyles(p.loras);
    setChosen(p.styles ?? []);
    setSteps(p.steps ?? null);
    setOwn(p.own ?? null);
    void begin(p.prompt, p.size ?? "square", null, p.loras, p.styles ?? [], p.steps, p.own);
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
  const keyboardHint = "Ctrl or ⌘ + Enter makes it too";

  // what can be done with the picture on the stage: three buttons and a menu (ADR-0093 decision 8)
  const resultActions: Action[] = shown
    ? [
        ...(onEditThis
          ? [
              {
                label: "Edit this",
                onSelect: () => onEditThis(shown),
                icon: <Pencil aria-hidden="true" />,
              },
            ]
          : []),
        ...(onAnimateThis
          ? [
              {
                label: "Animate this",
                onSelect: () => onAnimateThis(shown),
                icon: <Film aria-hidden="true" />,
              },
            ]
          : []),
        ...(canSave
          ? [
              {
                label: "Save a copy",
                onSelect: () => void save(shown),
                icon: <Save aria-hidden="true" />,
              },
            ]
          : []),
        ...(downloadHref && shown.id
          ? [
              {
                label: "Download",
                href: downloadHref(shown),
                download: true,
                icon: <Save aria-hidden="true" />,
              },
            ]
          : []),
        ...(canRunAgain(shown)
          ? [
              { label: "Make it again", onSelect: () => again(shown), disabled: working },
              { label: "Vary", onSelect: () => vary(shown), disabled: working },
            ]
          : []),
        {
          label: shown.favourite ? "Remove from favourites" : "Add to favourites",
          onSelect: () => void toggleFavourite(shown),
          icon: <Heart aria-hidden="true" />,
        },
        { label: "Use this prompt", onSelect: () => setPrompt(shown.prompt) },
        {
          label: recipeOpen ? "Hide the recipe" : "Recipe",
          onSelect: () => setRecipeOpen((v) => !v),
        },
      ]
    : [];

  const stageState: StageState = working
    ? {
        kind: "working",
        label: makingLabel("picture"),
        text: [job.text, took ? `the last one took ${took} s` : null].filter(Boolean).join(" · "),
        value: state.phase === "working" ? job.value : undefined,
        onStop: flow.reset,
      }
    : state.phase === "refused" && state.refusal
      ? {
          kind: "error",
          title: "We can't make that one",
          message: state.refusal.message,
          onReset: flow.reset,
        }
      : state.phase === "error" && state.error
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
                <img
                  src={shown.image_url}
                  alt={shown.prompt}
                  width={shown.width || undefined}
                  height={shown.height || undefined}
                  className="rounded-lg object-contain shadow-card"
                />
              ),
              caption: (
                <div className="grid gap-2">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="min-w-0 truncate">{shown.prompt}</span>
                    <span className="shrink-0 text-xs">
                      {shown.width}×{shown.height}
                      {shown.favourite ? " · favourite" : ""}
                    </span>
                  </div>
                  {recipeOpen ? <RecipeList image={shown} /> : null}
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
              icon: ImageIcon,
              title: appearsHere("picture"),
              text:
                mode === "text"
                  ? "Describe it on the left, then press Make the picture."
                  : "Choose a picture and say what to change, then press Make the picture.",
            };

  const recentItems: RecentItem[] = recent.map((img) => ({
    id: img.id,
    cover: <img src={img.thumb_url} alt="" className="size-full object-cover" />,
    label: `Open: ${img.prompt}`,
    current: picked?.id === img.id,
    onOpen: () => {
      flow.reset();
      setPicked(img);
    },
  }));

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* the model button, in the top bar; the modes and the library are the bar's tabs (ADR-0093, stage U2) */}
      <PageHeader className="flex h-14 shrink-0 items-center gap-4 border-b px-6 pt-1">
        <div className="flex min-w-0 items-center gap-2 ps-2 text-sm">{header}</div>
      </PageHeader>

      <MakeScreen
        title={COPY[mode].title}
        lead={COPY[mode].blurb}
        ask={
          <>
            {notices}

            {mode !== "text" ? (
              <PictureInput
                label={mode === "reference" ? "Picture 1" : "Your picture"}
                preview={mode !== "inpaint"}
                picture={pic.picture}
                status={pic.status}
                error={pic.error}
                dragging={dragging}
                onChoose={(f) => {
                  fromLibrary.current = null;
                  void pic.choose(f);
                }}
                onRemove={() => {
                  fromLibrary.current = null;
                  pic.clear();
                }}
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
                <p className="m-0 text-muted-foreground text-sm">
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
              hintText={
                mode === "inpaint"
                  ? "Only the painted area changes; a larger area works better than a small one."
                  : mode === "image"
                    ? "The result keeps the size of your picture."
                    : "Say what to see and how it should look."
              }
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
                    <Chip
                      key={s.id}
                      aria-pressed={size === s.id && !own}
                      onClick={() => {
                        setSize(s.id);
                        setOwn(null); // a shape chosen again: the size of one's own goes
                      }}
                    >
                      {s.label} <span className="opacity-85">{s.hint}</span>
                    </Chip>
                  ))}
                </div>
              </fieldset>
            ) : null}

            {stylesApi ? (
              <StylesSection
                api={stylesApi}
                chosen={chosen}
                onChange={setChosen}
                disabled={working}
                onOpenFolders={onOpenFolders}
                readOnly={stylesReadOnly}
                settings={{
                  size,
                  width: own?.width ?? null,
                  height: own?.height ?? null,
                  steps,
                }}
                onApplyLook={(l) => {
                  if (l.size) setSize(l.size);
                  setOwn(l.width && l.height ? { width: l.width, height: l.height } : null);
                  setSteps(l.steps ?? null);
                }}
                onUseWord={(word) =>
                  setPrompt((cur) =>
                    cur.toLowerCase().includes(word.toLowerCase())
                      ? cur
                      : cur.trim()
                        ? `${cur.trim()}, ${word}`
                        : word,
                  )
                }
              />
            ) : null}
            {(!stylesApi || stylesReadOnly) &&
            (loras.length > 0 || availableLoras.length > 0 || styles.length > 0) ? (
              // the styles are in view (ADR-0091): a row of the ones that are here, each with its strength once chosen
              <section className="grid gap-2" aria-label="Styles">
                <h2 className="m-0 font-semibold text-ui-lg">
                  Styles{" "}
                  <span className="font-normal text-muted-foreground">
                    {styles.length ? `(${styles.length} chosen)` : "(optional)"}
                  </span>
                </h2>
                <div className="grid gap-2">
                  {loras.map((l) => {
                    const on = styles.find((s) => s.name === l.name);
                    return (
                      <div key={l.name} className="grid gap-2 rounded-md border px-3 py-2">
                        <Checkbox
                          checked={Boolean(on)}
                          disabled={!on && styles.length >= MAX_STYLES}
                          onCheckedChange={() => toggleStyle(l.name)}
                          label={l.title}
                        />
                        {on ? (
                          <Slider
                            label={`Strength of ${l.title}`}
                            value={on.weight}
                            min={0.1}
                            max={2}
                            step={0.05}
                            format={(v) => v.toFixed(2)}
                            onValueChange={(v) => setStrength(l.name, v)}
                          />
                        ) : null}
                      </div>
                    );
                  })}
                  {styles
                    .filter((s) => !loras.some((l) => l.name === s.name))
                    .map((s) => (
                      <p key={s.name} className="m-0 rounded-md border px-3 py-2 text-sm">
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
                <p className="m-0 text-muted-foreground text-xs">
                  A style changes the look. Use ones made for the model in use; others give noise.
                  Up to {MAX_STYLES}.
                </p>
              </section>
            ) : null}

            <Experts
              title="Advanced"
              summary="steps, seed, how many, size"
              open={seed !== null || steps !== null || own !== null || undefined}
            >
              <AdvancedFields
                idBase={id}
                mode={mode}
                steps={steps}
                onSteps={setSteps}
                seed={seed}
                onSeed={setSeed}
                count={count}
                onCount={setCount}
                own={own}
                onOwn={setOwn}
                disabled={working}
              />
            </Experts>
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
              onClick={generate}
            >
              {working ? <Spinner /> : null}
              {makeLabel("picture")}
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
          </>
        }
        stage={<Stage state={stageState} className="w-full" />}
        recent={
          <RecentStrip
            title="Recent pictures"
            items={recentItems}
            onSeeAll={onOpenLibrary}
            empty="Nothing made here yet. Your first picture will show up here."
          />
        }
      />
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
          {r.styles && r.styles.length > 0 ? (
            <>
              <dt className="text-muted-foreground">Styles</dt>
              <dd>
                {r.styles.length === 1 ? "1 style" : `${r.styles.length} styles`} (
                {r.styles.map((x) => x.strength.toFixed(2)).join(", ")})
              </dd>
            </>
          ) : r.loras && r.loras.length > 0 ? (
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

const NUMBER =
  "h-9 w-24 rounded-md border bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** A whole number from a box, or null when it is empty or not a number. */
function wholeOf(text: string): number | null {
  const n = Number(text);
  return text.trim() && Number.isInteger(n) ? n : null;
}

const onGrid = (n: number | null) => n !== null && n >= 256 && n <= 2048 && n % 16 === 0;

/** Advanced (ADR-0091 decision 10): steps, seed, how many pictures and a size of one's own. */
function AdvancedFields({
  idBase,
  mode,
  steps,
  onSteps,
  seed,
  onSeed,
  count,
  onCount,
  own,
  onOwn,
  disabled,
}: {
  idBase: string;
  mode: ImageMode;
  steps: number | null;
  onSteps: (n: number | null) => void;
  seed: number | null;
  onSeed: (n: number | null) => void;
  count: number;
  onCount: (n: number) => void;
  own: { width: number; height: number } | null;
  onOwn: (o: { width: number; height: number } | null) => void;
  disabled: boolean;
}) {
  const sized = mode === "text" || mode === "reference";
  const [w, setW] = useState(own ? String(own.width) : "");
  const [h, setH] = useState(own ? String(own.height) : "");
  const had = useRef(own);
  useEffect(() => {
    if (own) {
      setW(String(own.width));
      setH(String(own.height));
    } else if (had.current) {
      setW(""); // a shape was chosen above: the boxes empty
      setH("");
    }
    had.current = own;
  }, [own]);
  const typed = Boolean(w.trim() || h.trim());
  function setSide(nextW: string, nextH: string) {
    setW(nextW);
    setH(nextH);
    const a = wholeOf(nextW);
    const b = wholeOf(nextH);
    onOwn(onGrid(a) && onGrid(b) ? { width: a as number, height: b as number } : null);
  }
  return (
    <div className="grid gap-3 text-sm">
      <label htmlFor={`${idBase}-steps`} className="flex flex-wrap items-center gap-2">
        <span className="w-28 text-muted-foreground">Steps</span>
        <input
          id={`${idBase}-steps`}
          aria-label="Steps"
          type="number"
          min={1}
          max={50}
          className={NUMBER}
          placeholder="4"
          value={steps ?? ""}
          disabled={disabled}
          onChange={(e) => {
            const n = wholeOf(e.target.value);
            onSteps(n !== null && n >= 1 && n <= 50 ? n : null);
          }}
        />
        <span className="text-muted-foreground">
          Empty: the model's own (4). More steps take longer.
        </span>
      </label>
      {mode === "text" ? (
        <label htmlFor={`${idBase}-seed`} className="flex flex-wrap items-center gap-2">
          <span className="w-28 text-muted-foreground">Seed</span>
          <input
            id={`${idBase}-seed`}
            aria-label="Seed"
            type="number"
            min={0}
            className={NUMBER}
            placeholder="Random"
            value={seed ?? ""}
            disabled={disabled}
            onChange={(e) => {
              const n = wholeOf(e.target.value);
              onSeed(n !== null && n >= 0 && n < 2 ** 31 ? n : null);
            }}
          />
          <span className="text-muted-foreground">
            The same seed and words make the same picture.
          </span>
        </label>
      ) : null}
      <fieldset className="m-0 flex flex-wrap items-center gap-2 border-0 p-0">
        <legend className="float-left w-28 text-muted-foreground">Pictures</legend>
        {Array.from({ length: MAX_PICTURES }, (_, i) => i + 1).map((n) => (
          <Chip key={n} aria-pressed={count === n} onClick={() => onCount(n)} disabled={disabled}>
            {n}
          </Chip>
        ))}
        {count > 1 ? (
          <span className="text-muted-foreground">
            One after the other{mode === "text" ? ", with consecutive seeds" : ""}.
          </span>
        ) : null}
      </fieldset>
      {sized ? (
        <div className="grid gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-28 text-muted-foreground">Size</span>
            <input
              aria-label="Width"
              type="number"
              min={256}
              max={2048}
              step={16}
              className={NUMBER}
              placeholder="width"
              value={w}
              disabled={disabled}
              onChange={(e) => setSide(e.target.value, h)}
            />
            <span aria-hidden="true">×</span>
            <input
              aria-label="Height"
              type="number"
              min={256}
              max={2048}
              step={16}
              className={NUMBER}
              placeholder="height"
              value={h}
              disabled={disabled}
              onChange={(e) => setSide(w, e.target.value)}
            />
            {typed ? (
              <button
                type="button"
                className="text-muted-foreground underline underline-offset-4"
                onClick={() => setSide("", "")}
              >
                Use the shape above
              </button>
            ) : null}
          </div>
          <p className={`m-0 ${typed && !own ? "text-warn" : "text-muted-foreground"}`}>
            {typed && !own
              ? "Width and height: 256 to 2048, in steps of 16 (like 1280 and 720)."
              : own
                ? `${own.width} × ${own.height}, instead of the shape above.`
                : "Empty: the shape chosen above."}
          </p>
        </div>
      ) : null}
    </div>
  );
}
