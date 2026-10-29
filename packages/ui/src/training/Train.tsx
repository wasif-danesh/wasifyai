"use client";

import {
  type TrainDataset,
  type TrainKind,
  type TrainPicture,
  type TrainRun,
  type TrainStatus,
  type TrainedModel,
  type TrainingApi,
  gigabytes,
} from "@wasifyai/client";
import { Film, FlaskConical, Trash2, Upload } from "lucide-react";
import { type DragEvent, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { JobMeter, WorkingCard } from "../components/create";
import { Notice } from "../components/notice";
import { Stepper } from "../components/stepper";
import type { ImageFlowApi } from "../hooks/use-image-flow";
import { actions, chips, eyebrow, field, fieldLabel, hint, panel } from "../styles";
import { BackInBar } from "../window-bar";
import { CheckIt, EvaluationLine } from "./CheckIt";
import { Choose } from "./Choose";
import { Decide, DecideResult } from "./Decide";
import { SetupCard } from "./SetupCard";
import { TryIt } from "./TryIt";
import { Writing, WritingResult } from "./Writing";
import { useChoices } from "./use-choices";
import { useTrainingSetup } from "./use-setup";
import { type TrainState, useTraining } from "./use-training";
import { type VideoTraining, useVideoTraining } from "./use-video-training";

const INPUT =
  "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30";

const KIND_LABEL: Record<TrainKind, { title: string; note: string }> = {
  character: { title: "A character, pet, person or thing", note: "It appears in every picture." },
  style: { title: "A style", note: "The look of the pictures: how they are drawn or painted." },
  object: { title: "An idea or an object", note: "One kind of thing, shown in different places." },
};

/** The same notes for a set made for the video model. */
const KIND_NOTE_VIDEO: Record<TrainKind, string> = {
  character: "It appears in every picture and clip.",
  style: "The look of the pictures and clips: how they are drawn, painted or filmed.",
  object: "One kind of thing, shown in different places.",
};

/**
 * What can be taught, one card each (ADR-0073): the label says which kind of model it makes, the
 * headline says what the person gets. Only pictures are built; the others say when they are coming.
 */
type Family = {
  id: string;
  label: string;
  title: string;
  text: string;
  live?: boolean;
  /** which screen Start opens: the pictures (default), the writing examples, the decisions or a set for the video model */
  start?: "writing" | "decide" | "video";
  soon?: string;
};

const FAMILIES: Family[] = [
  {
    id: "image",
    label: "Image model training",
    title: "Make my own character or style",
    text: "Add 15 to 25 pictures of your character, pet, art style or object. Then write its magic word in a prompt to draw it.",
    live: true,
  },
  {
    id: "language",
    label: "Language model training",
    title: "Teach it from examples",
    text: "Show it questions and the answers you want. It learns to answer that way, on this computer.",
    live: true,
    start: "writing",
  },
  {
    id: "decision",
    label: "Decision model training",
    title: "Teach it to decide",
    text: "Give it texts and the right answers, such as yes or no, a category or a score. It learns to answer new texts the same way, and says how sure it is.",
    live: true,
    start: "decide",
  },
  {
    id: "video",
    label: "Video model training",
    title: "Make my own look or motion for video",
    text: "Add pictures and short clips of your character, style or motion. Then write its magic word in a video prompt to make it.",
    live: true,
    start: "video",
  },
];

export type TrainProps = {
  api: TrainingApi;
  /** Where the work is done: on this computer (the desktop) or on a service's worker (the web). */
  place?: "device" | "service";
  onOpenLibrary?: () => void;
  /** The image engine's run client: with it, a taught model can be tried (drawn with and without). */
  runs?: ImageFlowApi;
  /** how often to read again while the descriptions are written or a run goes (milliseconds) */
  pollMs?: number;
};

type Hook = ReturnType<typeof useTraining>;

/** Teach the app something of your own (ADR-0073): today a character, style or object from pictures. */
export function Train({ api, place = "device", onOpenLibrary, runs, pollMs }: TrainProps) {
  const t = useTraining(api, pollMs);
  const { state } = t;
  // the trainer's own component: offered while training is not ready (a desktop engine), read again once set up
  const notReady = state.status !== null && !state.status.ready;
  const setup = useTrainingSetup(api, place === "device", () => void t.refresh(), pollMs);
  const video = useVideoTraining(api, true, state.status, pollMs, place === "device");
  const showingRun = state.run !== null;
  const [screen, setScreen] = useState<"writing" | "decide" | null>(null);
  // the set-up a card's "Set up" opened (ADR-0093 U10: shown when asked, not always)
  const [setting, setSetting] = useState<"image" | "video" | null>(null);
  const home = !screen && !state.current && !showingRun;
  const writing = screen !== null;
  // a set for the video model: the picture trainer's notices do not apply to it
  const forVideo = state.current?.family === "video";
  return (
    <div className="mx-auto grid w-full max-w-5xl gap-5 p-[clamp(1rem,3vw,2rem)]">
      {home || (showingRun && state.run?.status === "working") ? null : (
        <BackInBar
          label="Train models"
          onBack={() => {
            if (screen) {
              setScreen(null);
              void t.refresh();
            } else void t.leave();
          }}
        />
      )}
      <header className="grid gap-1.5">
        <h1 className="font-semibold text-step-2">
          {screen === "writing"
            ? "Teach it from examples"
            : screen === "decide"
              ? "Teach it to decide"
              : state.current || showingRun
                ? state.current?.family === "video"
                  ? "Make my own look or motion for video"
                  : "Make my own character or style"
                : "Teach the app something of your own"}
        </h1>
        {writing ? null : state.current || showingRun ? (
          <p className="max-w-3xl text-muted-foreground">
            {state.current?.family === "video"
              ? "Add pictures and short clips and nothing else: the app describes them, suggests a magic word and teaches the video model. "
              : "Add pictures and nothing else: the app describes them, suggests a magic word and teaches the image model. "}
            {place === "device"
              ? "It is learnt on this computer; your pictures are not sent anywhere."
              : "It is learnt on the service's graphics card."}
          </p>
        ) : (
          <p className="max-w-3xl text-muted-foreground">
            Choose what to teach and add your own examples. The app does the rest.{" "}
            {place === "device"
              ? "It is learnt on this computer; your pictures and examples are not sent anywhere."
              : "It is learnt on the service's graphics card."}
          </p>
        )}
      </header>

      {writing || forVideo ? null : state.status?.preview ? (
        <Notice tone="info" title="A preview">
          Training runs every step and shows sample pictures, but it does not learn yet, so the
          models it makes are not real. The real trainer is coming.
        </Notice>
      ) : null}
      {writing || forVideo ? null : notReady &&
        setup.setup &&
        setup.setup.plan.supported &&
        !setup.setup.installed &&
        (!home || setting === "image" || installing(setup.setup)) ? (
        <SetupCard
          setup={setup.setup}
          error={setup.error}
          onInstall={(bytes) => void setup.install(bytes)}
          onCancel={() => void setup.cancel()}
        />
      ) : notReady && !home ? (
        <Notice tone="warn" title="Training is not ready">
          {setup.setup?.problem ?? state.status?.problem ?? "It could not be started."}
        </Notice>
      ) : null}
      {!writing && !forVideo && !home && state.status?.fit?.verdict === "too_big" ? (
        <Notice tone="warn" title="Not enough memory to teach a model">
          {state.status.fit.reason}
        </Notice>
      ) : null}
      {forVideo && video.status?.fit?.verdict === "too_big" ? (
        <Notice tone="warn" title="Not enough memory to teach a model">
          {video.status.fit.reason}
        </Notice>
      ) : null}
      {!writing && state.error ? (
        <Notice tone="error" title="That did not work">
          {state.error}
        </Notice>
      ) : null}

      {screen === "writing" ? (
        <Writing api={api} pollMs={pollMs} />
      ) : screen === "decide" ? (
        <Decide api={api} pollMs={pollMs} />
      ) : state.loading ? (
        <output className="text-muted-foreground">Looking at training…</output>
      ) : showingRun && state.run ? (
        <RunView t={t} run={state.run} onOpenLibrary={onOpenLibrary} runs={runs} api={api} />
      ) : state.current ? (
        <MakeView t={t} status={state.status} api={api} video={video} />
      ) : (
        <Home
          t={t}
          runs={runs}
          setup={setup}
          video={video}
          api={api}
          setting={setting}
          place={place}
          onSetUp={(which) => setSetting(setting === which ? null : which)}
          onStart={{
            writing: place === "device" ? () => setScreen("writing") : undefined,
            decide: place === "device" ? () => setScreen("decide") : undefined,
            video: () => void t.newDataset("character", "video"),
          }}
        />
      )}
    </div>
  );
}

// ---- the front door -----------------------------------------------------------------------------

function Home({
  t,
  runs,
  setup,
  video,
  api,
  onStart,
  setting,
  onSetUp,
  place,
}: {
  t: Hook;
  runs?: ImageFlowApi;
  setup: ReturnType<typeof useTrainingSetup>;
  video: VideoTraining;
  api: TrainingApi;
  onStart?: { writing?: () => void; decide?: () => void; video?: () => void };
  setting?: "image" | "video" | null;
  onSetUp?: (which: "image" | "video") => void;
  place: "device" | "service";
}) {
  const { state } = t;
  const ready = state.status?.ready === true;
  // what each card can do here, in one look (ADR-0093 U10): it works, it needs a step first, or it cannot
  const look = (f: Family): CardLook => {
    if (!f.live) return { tone: "no", text: f.soon ?? "Soon" };
    if ((f.start === "writing" || f.start === "decide") && !onStart?.[f.start])
      return { tone: "no", text: "On the desktop app" };
    if (f.start === "writing" || f.start === "decide") return { tone: "ok", text: "Works here" };
    const status = f.start === "video" ? video.status : state.status;
    const plan = f.start === "video" ? video.setup.setup : setup.setup;
    if (status === null) return { tone: "no", text: "Looking…" };
    if (status.fit?.verdict === "too_big")
      return { tone: "no", text: `Not enough memory: ${status.fit.reason}` };
    if (status.ready) return { tone: "ok", text: "Works here" };
    const missing = "needs" in status ? status.needs.filter((n) => !n.have) : [];
    if (missing.length > 0)
      return {
        tone: "step",
        text: `Needs a step: ${status.problem ?? ""} ${missing.map((n) => `${n.name} (${gigabytes(n.bytes)}). ${n.how}`).join(" ")}`,
      };
    if (plan?.plan.supported && !plan.installed)
      return {
        tone: "step",
        text:
          plan.progress.state === "installing"
            ? "Setting up…"
            : `Needs a step: set it up first (${gigabytes(plan.plan.bytes)} download)`,
        setUp: f.start === "video" ? "video" : "image",
      };
    return {
      tone: "no",
      text: `${place === "device" ? "Not on this computer" : "Not on this service"}: ${plan?.problem ?? status.problem ?? "it could not be started"}`,
    };
  };
  const filled = state.datasets.filter((d) => d.pictures > 0);
  const empty = state.datasets.filter((d) => d.pictures === 0);
  const setRow = (d: (typeof state.datasets)[number]) => (
    <li key={d.id} className="flex flex-wrap items-center gap-3 rounded-xl border p-3">
      <span className="min-w-0 flex-1">
        <strong>{d.name || "Untitled set"}</strong>{" "}
        <span className="text-muted-foreground">
          · {KIND_LABEL[d.kind].title.toLowerCase()} · {d.pictures}{" "}
          {d.family === "video"
            ? d.pictures === 1
              ? "picture or clip"
              : "pictures and clips"
            : d.pictures === 1
              ? "picture"
              : "pictures"}
        </span>
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={`Continue ${d.name || "the set"}`}
        onClick={() => void t.openDataset(d.id)}
      >
        Continue
      </Button>
      <Sure label="Remove" name={d.name || "the set"} onSure={() => void t.removeDataset(d.id)} />
    </li>
  );
  return (
    <>
      <section aria-label="What to teach" className="grid gap-3 md:grid-cols-2">
        {FAMILIES.map((f) => {
          const l = look(f);
          const busy =
            state.busy !== null ||
            (f.start === "video" && (video.status?.busy === true || state.status?.busy === true));
          return (
            <div
              key={f.id}
              data-state={l.tone}
              className={cn(panel, "content-start", l.tone === "no" && "opacity-80")}
              aria-disabled={l.tone === "no" ? "true" : undefined}
            >
              <span className="text-muted-foreground text-xs">{f.label}</span>
              <h2 className="m-0 font-semibold text-lg">{f.title}</h2>
              <p className="m-0 text-muted-foreground">{f.text}</p>
              <p className="m-0 flex items-start gap-2 text-sm" data-slot="card-state">
                <span
                  aria-hidden="true"
                  className={cn(
                    "mt-1.5 size-2 shrink-0 rounded-full",
                    l.tone === "ok"
                      ? "bg-ok"
                      : l.tone === "step"
                        ? "bg-warn"
                        : "bg-muted-foreground",
                  )}
                />
                <span className={l.tone === "ok" ? undefined : "text-muted-foreground"}>
                  {l.text}
                </span>
              </p>
              {l.tone === "ok" ? (
                <div className={actions}>
                  <Button
                    type="button"
                    aria-label={
                      f.start === "writing"
                        ? "Start: teach it from examples"
                        : f.start === "decide"
                          ? "Start: teach it to decide"
                          : f.start === "video"
                            ? "Start: make my own look or motion for video"
                            : undefined
                    }
                    disabled={(f.start === undefined && !ready) || busy}
                    onClick={
                      f.start === "writing" || f.start === "decide" || f.start === "video"
                        ? onStart?.[f.start]
                        : () => void t.newDataset()
                    }
                  >
                    Start
                  </Button>
                </div>
              ) : l.setUp && onSetUp ? (
                <div className={actions}>
                  <Button
                    type="button"
                    variant="outline"
                    aria-label={`Set up: ${f.title}`}
                    aria-expanded={setting === l.setUp}
                    onClick={() => onSetUp(l.setUp as "image" | "video")}
                  >
                    Set up
                  </Button>
                </div>
              ) : null}
            </div>
          );
        })}
      </section>

      {setting === "video" || installing(video.setup.setup) ? (
        <VideoSetup video={video} onStart={onStart?.video !== undefined} />
      ) : null}

      {state.paused.length > 0 ? (
        <section aria-label="Paused" className="grid gap-2">
          <h2 className="m-0 font-semibold text-lg">Paused</h2>
          <ul className="m-0 grid list-none gap-2 p-0">
            {state.paused.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 rounded-xl border p-3">
                <span className="min-w-0 flex-1">
                  <strong>{r.stage || "Paused"}</strong>{" "}
                  <span className="text-muted-foreground">
                    · its place is kept, and it carries on from there
                  </span>
                </span>
                <Button type="button" size="sm" onClick={() => void t.resume(r.id)}>
                  Carry on
                </Button>
                <Sure label="Discard" name="this run" onSure={() => void t.discard(r.id)} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {state.datasets.length > 0 ? (
        <section aria-label="Sets of pictures" className="grid gap-2">
          <h2 className="m-0 font-semibold text-lg">Sets of pictures and clips</h2>
          {filled.length > 0 ? (
            <ul className="m-0 grid list-none gap-2 p-0">{filled.map(setRow)}</ul>
          ) : null}
          {empty.length > 0 ? (
            // sets started and left with nothing in them wait folded, so the ones in use are seen (ADR-0093 U10)
            <details className="group">
              <summary className="cursor-pointer text-muted-foreground text-sm">
                {empty.length === 1 ? "1 empty set" : `${empty.length} empty sets`}
              </summary>
              <ul className="m-0 mt-2 grid list-none gap-2 p-0">{empty.map(setRow)}</ul>
            </details>
          ) : null}
        </section>
      ) : null}

      <section aria-label="My models" className="grid gap-2">
        <h2 className="m-0 font-semibold text-lg">My models</h2>
        {state.models.length === 0 ? (
          <p className="m-0 text-muted-foreground">Nothing taught yet.</p>
        ) : (
          <ul className="m-0 grid list-none gap-2 p-0 md:grid-cols-2">
            {state.models.map((m) => (
              <ModelCard key={m.id} model={m} t={t} runs={runs} api={api} />
            ))}
          </ul>
        )}
      </section>

      {(setup.setup && (setup.setup.tool === "managed" || setup.setup.base === "managed")) ||
      (video.setup.setup &&
        (video.setup.setup.tool === "managed" || video.setup.setup.base === "managed")) ? (
        <section aria-label="Training tools" className="grid gap-2">
          <h2 className="m-0 font-semibold text-lg">Training tools</h2>
          <p className={hint}>
            The trainers and the small files they learn with are kept in the app's own folder.
            Removing them gives the space back; you can set them up again whenever you want to teach
            something. Your pictures, clips and the models you taught are kept.
          </p>
          <div className={actions}>
            {setup.setup && (setup.setup.tool === "managed" || setup.setup.base === "managed") ? (
              <Sure
                label="Remove"
                name="the trainer and the picture model"
                onSure={() => void setup.remove()}
              />
            ) : null}
            {video.setup.setup &&
            (video.setup.setup.tool === "managed" || video.setup.setup.base === "managed") ? (
              <Sure
                label="Remove"
                name="the video trainer"
                onSure={() => void video.setup.remove()}
              />
            ) : null}
          </div>
        </section>
      ) : null}
    </>
  );
}

/**
 * What the video model needs before it can be taught, shown under the cards while it cannot be: the video
 * trainer's set-up (sizes first, nothing fetched before the button), and the video model itself, which the
 * Video screens already get and this screen does not fetch.
 */
type CardLook = { tone: "ok" | "step" | "no"; text: string; setUp?: "image" | "video" };

const installing = (s: { progress: { state: string } } | null | undefined) =>
  s?.progress.state === "installing" || s?.progress.state === "failed";

function VideoSetup({ video, onStart }: { video: VideoTraining; onStart: boolean }) {
  const { status, setup } = video;
  if (!onStart || status === null || status.ready) return null;
  const missing = status.needs.filter((n) => !n.have);
  const state = setup.setup;
  return (
    <section aria-label="Set up video training" className="grid gap-3">
      {state?.plan.supported && !state.installed && state.progress.state !== "ready" ? (
        <SetupCard
          setup={state}
          error={setup.error}
          onInstall={(bytes) => void setup.install(bytes)}
          onCancel={() => void setup.cancel()}
          title="Set up video training"
          intro="Teaching the video model needs a trainer. It is not in the app. It is downloaded once, every file checked, and kept in the app's own folder. Nothing else on your computer is changed, and your pictures and clips are not sent anywhere."
        />
      ) : (
        <Notice tone="warn" title="Video training is not ready">
          {state?.problem ?? status.problem ?? "It could not be started."}
        </Notice>
      )}
      {missing.map((n) => (
        <Notice key={n.name} tone="info" title="The video model is needed">
          {n.name} ({gigabytes(n.bytes)}) is what the Video screens use. {n.how}
        </Notice>
      ))}
    </section>
  );
}

/** A button that asks once more before it does something that cannot be undone. */
function Sure({ label, name, onSure }: { label: string; name: string; onSure: () => void }) {
  const [asked, setAsked] = useState(false);
  return asked ? (
    <span className="flex items-center gap-1.5">
      <Button
        type="button"
        size="sm"
        variant="outline"
        aria-label={`Yes, ${label.toLowerCase()} ${name}`}
        onClick={onSure}
      >
        Yes, {label.toLowerCase()}
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => setAsked(false)}>
        Not now
      </Button>
    </span>
  ) : (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      aria-label={`${label} ${name}`}
      onClick={() => setAsked(true)}
    >
      <Trash2 className="size-4" aria-hidden="true" />
      {label}
    </Button>
  );
}

function ModelCard({
  model: m,
  t,
  runs,
  api,
}: { model: TrainedModel; t: Hook; runs?: ImageFlowApi; api: TrainingApi }) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(m.name);
  const id = useId();
  return (
    <li className="grid gap-2 rounded-xl border p-4">
      <div className="flex flex-wrap items-center gap-2">
        {renaming ? (
          <>
            <label htmlFor={id} className="sr-only">
              Name
            </label>
            <input
              id={id}
              className={INPUT}
              value={name}
              maxLength={200}
              onChange={(e) => setName(e.target.value)}
            />
            <Button
              type="button"
              size="sm"
              disabled={!name.trim()}
              onClick={() => {
                void t.renameModel(m.id, name.trim());
                setRenaming(false);
              }}
            >
              Save
            </Button>
          </>
        ) : (
          <strong className="min-w-0 flex-1 truncate">{m.name}</strong>
        )}
        {m.preview ? (
          <span className="rounded-full border px-2 py-0.5 text-xs">Preview</span>
        ) : null}
      </div>
      {m.kind === "writing" ? (
        <p className={hint}>
          Taught from {m.card.dataset.examples ?? 0} examples · {m.card.base_title}.
        </p>
      ) : m.kind === "decision" ? (
        <p className={hint}>
          Answers “{m.card.question?.text ?? ""}” · taught from {m.card.dataset.examples ?? 0}{" "}
          examples · {m.card.base_title}.
        </p>
      ) : (
        <>
          <p className="m-0 text-sm">
            Magic word: <code>{m.trigger_word}</code>
            {m.card.family === "video" ? " (use it in a video prompt)" : ""}
          </p>
          <p className={hint}>
            {KIND_LABEL[m.kind].title}, {m.card.dataset.pictures}{" "}
            {m.card.family === "video" ? "pictures and clips" : "pictures"}, {m.card.steps} steps,{" "}
            {m.card.base_title}.{m.card.note ? ` ${m.card.note}` : ""}
          </p>
        </>
      )}
      <EvaluationLine model={m} />
      <div className={actions}>
        {renaming ? null : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-label={`Rename ${m.name}`}
            onClick={() => setRenaming(true)}
          >
            Rename
          </Button>
        )}
        <Sure label="Remove" name={m.name} onSure={() => void t.removeModel(m.id)} />
      </div>
      {m.kind === "writing" ? (
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer font-medium text-sm">See what it learnt</summary>
          <div className="pt-3">
            <WritingResult model={m} api={api} />
          </div>
        </details>
      ) : m.kind === "decision" ? (
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer font-medium text-sm">See what it learnt</summary>
          <div className="pt-3">
            <DecideResult model={m} api={api} />
          </div>
        </details>
      ) : runs && !m.preview && m.card.family !== "video" ? (
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer font-medium text-sm">Check and try it</summary>
          <div className="grid gap-5 pt-3">
            <CheckIt model={m} api={api} runs={runs} onSaved={() => void t.refresh()} />
            <TryIt model={m} runs={runs} />
          </div>
        </details>
      ) : null}
    </li>
  );
}

// ---- the set being made: add pictures, check, teach ---------------------------------------------

function MakeView({
  t,
  status,
  api,
  video,
}: {
  t: Hook;
  status: TrainStatus | null;
  api: TrainingApi;
  video: VideoTraining;
}) {
  const d = t.state.current as TrainDataset;
  const isVideo = d.family === "video";
  const [step, setStep] = useState<1 | 2>(1);
  const min = isVideo ? (video.status?.min_items ?? 8) : (status?.min_pictures ?? 8);
  return (
    <>
      <Stepper
        steps={[isVideo ? "Add pictures and clips" : "Add pictures", "Check", "Teach"]}
        current={step - 1}
        onStep={(n) => n === 0 && setStep(1)}
      />
      {step === 1 ? (
        <PicturesStep t={t} d={d} min={min} onNext={() => setStep(2)} video={isVideo} />
      ) : (
        <CheckStep
          t={t}
          d={d}
          status={status}
          onBack={() => setStep(1)}
          api={api}
          video={isVideo ? video : undefined}
        />
      )}
    </>
  );
}

function PicturesStep({
  t,
  d,
  min,
  onNext,
  video = false,
}: { t: Hook; d: TrainDataset; min: number; onNext: () => void; video?: boolean }) {
  const [over, setOver] = useState(false);
  const pickerId = useId();
  const items = d.items ?? [];
  const problems = items.filter((i) => i.suggest_remove).length;
  const take = (files: FileList | File[] | null) => {
    const list = files ? Array.from(files) : [];
    if (list.length > 0) void t.addPictures(list);
  };
  const drop = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    setOver(false);
    take(e.dataTransfer.files);
  };
  return (
    <section className={panel} aria-label={video ? "Add pictures and clips" : "Add pictures"}>
      <section
        aria-label={video ? "Drop pictures and clips here" : "Drop pictures here"}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cn(
          "grid justify-items-center gap-2 rounded-xl border border-dashed p-8 text-center",
          over && "border-ring bg-accent",
        )}
      >
        <Upload className="size-6 text-muted-foreground" aria-hidden="true" />
        <p className="m-0">
          {video
            ? "Drop pictures and clips here, or choose them."
            : "Drop pictures here, or choose them."}
        </p>
        <input
          id={pickerId}
          type="file"
          multiple
          accept={
            video
              ? "image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm"
              : "image/png,image/jpeg,image/webp"
          }
          hidden
          aria-label={video ? "Choose pictures and clips" : "Choose pictures"}
          onChange={(e) => {
            take(e.target.files);
            e.target.value = "";
          }}
        />
        <Button
          type="button"
          variant="outline"
          disabled={t.state.busy === "picture"}
          onClick={() => document.getElementById(pickerId)?.click()}
        >
          {t.state.busy === "picture"
            ? "Adding…"
            : video
              ? "Choose pictures and clips"
              : "Choose pictures"}
        </Button>
        <p className={hint}>
          {video
            ? `A few pictures and 5 to 15 short clips of 2 to 10 seconds is plenty, and at least ${min} in all. The app learns from up to three one-second pieces of each clip. MP4, MOV or WebM; PNG, JPEG or WebP.`
            : `15 to 25 good ones is plenty, and at least ${min}. PNG, JPEG or WebP, under 20 MB each.`}
        </p>
      </section>

      {items.length > 0 ? (
        <>
          <p className="m-0" aria-live="polite">
            {items.length}{" "}
            {video
              ? items.length === 1
                ? "picture or clip"
                : "pictures and clips"
              : items.length === 1
                ? "picture"
                : "pictures"}
            .{problems > 0 ? ` ${problems} with a problem.` : " All good."}
          </p>
          <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-3 md:grid-cols-4">
            {items.map((i) => (
              <PictureTile
                key={i.id}
                item={i}
                src={t.state.urls[`item:${i.id}`]}
                onRemove={() => void t.removePicture(i.id)}
              />
            ))}
          </ul>
          {problems > 0 ? (
            <div>
              <Button type="button" variant="outline" onClick={() => void t.removeWithProblems()}>
                Remove the {problems} with a problem
              </Button>
            </div>
          ) : null}
        </>
      ) : null}

      <div className={actions}>
        <Button type="button" size="lg" disabled={items.length < min} onClick={onNext}>
          Next
        </Button>
        {items.length < min ? (
          <span className="text-muted-foreground">
            Add at least {min} {video ? "pictures and clips" : "pictures"} ({min - items.length}{" "}
            more).
          </span>
        ) : null}
      </div>
    </section>
  );
}

function PictureTile({
  item,
  src,
  onRemove,
}: { item: TrainPicture; src?: string; onRemove: () => void }) {
  return (
    <li className="grid gap-1.5">
      <div className="relative aspect-square overflow-hidden rounded-lg border bg-muted">
        {src ? <img src={src} alt={item.name} className="size-full object-cover" /> : null}
        {item.media === "clip" ? (
          <span className="absolute start-1 bottom-1 flex items-center gap-1 rounded-full bg-background/90 px-2 py-0.5 text-xs shadow-xs">
            <Film className="size-3" aria-hidden="true" />
            {item.seconds ? `${item.seconds.toFixed(1)} s` : "Clip"}
          </span>
        ) : null}
        <button
          type="button"
          aria-label={`Remove ${item.name}`}
          onClick={onRemove}
          className="absolute end-1 top-1 rounded-full bg-background/90 p-1.5 shadow-xs hover:bg-background"
        >
          <Trash2 className="size-4" aria-hidden="true" />
        </button>
      </div>
      <span className={cn("text-xs", item.suggest_remove ? "text-warn" : "text-muted-foreground")}>
        {item.checks[0]?.message}
        {item.checks.length > 1
          ? ` ${item.checks
              .slice(1)
              .map((c) => c.message)
              .join(" ")}`
          : ""}
      </span>
    </li>
  );
}

function CheckStep({
  t,
  d,
  status,
  onBack,
  api,
  video,
}: {
  t: Hook;
  d: TrainDataset;
  status: TrainStatus | null;
  onBack: () => void;
  api: TrainingApi;
  /** a set for the video model: its status and set-up */
  video?: VideoTraining;
}) {
  const [own, setOwn] = useState("");
  const isVideo = video !== undefined;
  const choosing = useChoices(api, d.kind, isVideo ? "video" : "image");
  const nameId = useId();
  const ownId = useId();
  const items = d.items ?? [];
  const suggestions = d.suggestions ?? [];
  const waiting = items.filter(
    (i) => i.caption_state === "none" || i.caption_state === "failed",
  ).length;
  const writing = d.writing || t.state.busy === "captions";
  const estimate = d.estimate ?? status?.estimates?.[d.kind] ?? "";
  const noVideo = video?.status && !video.status.ready ? video.status.problem : null;
  const preflight = (video ? video.status?.preflight : status?.preflight) ?? null;
  return (
    <section className={panel} aria-label="Check">
      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>What is it?</legend>
        <div className={chips}>
          {(Object.keys(KIND_LABEL) as TrainKind[]).map((k) => (
            <Chip key={k} aria-pressed={d.kind === k} onClick={() => void t.change({ kind: k })}>
              {KIND_LABEL[k].title}
            </Chip>
          ))}
        </div>
        <p className={hint}>{isVideo ? KIND_NOTE_VIDEO[d.kind] : KIND_LABEL[d.kind].note}</p>
      </fieldset>

      <div className={field}>
        <label htmlFor={nameId} className={fieldLabel}>
          A name for it (optional)
        </label>
        <input
          id={nameId}
          className={cn(INPUT, "max-w-sm")}
          defaultValue={d.name}
          maxLength={60}
          placeholder="Marlo"
          onBlur={(e) => {
            if (e.target.value !== d.name) void t.change({ name: e.target.value });
          }}
        />
      </div>

      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>The magic word</legend>
        <p className={hint}>
          {isVideo
            ? `When you write this word in a video prompt, the app makes your ${d.name || "character"}.`
            : `When you write this word in a prompt, the app draws your ${d.name || "character"}.`}
        </p>
        <div className={chips}>
          {suggestions.map((w) => (
            <Chip
              key={w}
              aria-pressed={d.trigger_word === w}
              onClick={() => void t.change({ trigger_word: w })}
            >
              {w}
            </Chip>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={ownId} className="text-sm">
            Or type your own
          </label>
          <input
            id={ownId}
            className={cn(INPUT, "max-w-[12rem]")}
            value={own}
            maxLength={12}
            onChange={(e) => setOwn(e.target.value.toLowerCase())}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={own.length < 4}
            onClick={() => void t.change({ trigger_word: own })}
          >
            Use this word
          </Button>
        </div>
        <p className="m-0 text-sm" aria-live="polite">
          {d.trigger_word ? (
            <>
              Chosen: <code>{d.trigger_word}</code>
            </>
          ) : (
            "Choose one."
          )}
        </p>
      </fieldset>

      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="m-0 font-semibold text-lg">The descriptions</h2>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={writing || items.length === 0}
            onClick={() => void t.writeCaptions(waiting === 0 ? { again: true } : undefined)}
          >
            {writing
              ? "Writing…"
              : waiting === 0
                ? "Describe all again"
                : `Write the descriptions (${waiting})`}
          </Button>
        </div>
        <p className={hint}>
          {isVideo
            ? "The app describes each picture and clip in words. Read them and change any you like; the magic word goes first."
            : "The app describes each picture in words. Read them and change any you like; the magic word goes first."}
        </p>
        <ul className="m-0 grid list-none gap-3 p-0">
          {items.map((i) => (
            <CaptionRow key={i.id} item={i} src={t.state.urls[`item:${i.id}`]} t={t} />
          ))}
        </ul>
      </div>

      {preflight ? (
        <>
          {preflight.blockers.map((why) => (
            <Notice key={why} tone="error" title="It cannot start now">
              {why}
            </Notice>
          ))}
          {preflight.warnings.map((why) => (
            <Notice key={why} tone="warn" title="Before you start">
              {why}
            </Notice>
          ))}
        </>
      ) : null}
      {noVideo ? (
        <Notice tone="warn" title="It cannot start now">
          {noVideo}
        </Notice>
      ) : null}
      <Choose c={choosing} />
      <div className={actions}>
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button
          type="button"
          size="lg"
          disabled={
            d.missing !== null ||
            writing ||
            t.state.busy === "run" ||
            t.state.status?.busy === true ||
            video?.status?.ready === false ||
            video?.status?.busy === true ||
            preflight?.ok === false
          }
          onClick={() => void t.teach(choosing.choice)}
        >
          Teach it
        </Button>
        <span className="text-muted-foreground">
          {d.missing ??
            `${estimate}. ${preflight?.pauses ?? (isVideo ? "Chat, image and video making pause while it learns." : "Chat and image making pause while it learns.")}`}
        </span>
      </div>
    </section>
  );
}

function CaptionRow({ item, src, t }: { item: TrainPicture; src?: string; t: Hook }) {
  const id = useId();
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? item.caption;
  const state = item.caption_state;
  return (
    <li className="grid grid-cols-[5rem_1fr] gap-3">
      <div className="aspect-square overflow-hidden rounded-lg border bg-muted">
        {src ? <img src={src} alt={item.name} className="size-full object-cover" /> : null}
      </div>
      <div className="grid gap-1">
        <label htmlFor={id} className="sr-only">
          Description of {item.name}
        </label>
        <textarea
          id={id}
          className={cn(INPUT, "min-h-16")}
          value={state === "writing" ? "" : shown}
          placeholder={state === "writing" ? "Writing…" : "No description yet."}
          disabled={state === "writing"}
          maxLength={2000}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => {
            if (text !== null && text !== item.caption) void t.editCaption(item.id, text);
            setText(null);
          }}
        />
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>
            {state === "failed"
              ? (item.caption_error ?? "It could not be described.")
              : state === "edited"
                ? "Changed by you."
                : state === "done"
                  ? "Written by the app."
                  : ""}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={state === "writing"}
            aria-label={`Describe again ${item.name}`}
            onClick={() => void t.writeCaptions({ again: true, pictureIds: [item.id] })}
          >
            Describe again
          </Button>
        </div>
      </div>
    </li>
  );
}

// ---- the run, and "use it" ----------------------------------------------------------------------

function RunView({
  t,
  run,
  onOpenLibrary,
  runs,
  api,
}: {
  t: Hook;
  run: TrainRun;
  onOpenLibrary?: () => void;
  runs?: ImageFlowApi;
  api: TrainingApi;
}) {
  const working = run.status === "working";
  const model = t.state.models.find((m) => m.id === run.model_id) ?? null;
  const samples = run.samples
    .map((name) => ({ name, src: t.state.urls[`sample:${run.id}/${name}`] }))
    .filter((s) => s.src);
  return (
    <section className={panel} aria-label="The run">
      {working ? (
        <WorkingCard label="Teaching" onCancel={() => void t.stop()}>
          <JobMeter
            title="Teaching the model"
            text={`Step ${run.step} of ${run.steps}`}
            value={run.progress}
            label="Teaching progress"
          />
          <p className={hint}>
            {run.stage || "Starting"}. About {run.estimate.replace(/^About /, "").toLowerCase()} in
            all.
          </p>
          {run.preview || t.state.status?.can_pause === false ? null : (
            <div className={actions}>
              <Button type="button" variant="outline" onClick={() => void t.pause()}>
                Pause
              </Button>
              <span className="text-muted-foreground text-sm">
                Pause keeps its place so you can carry on later; Cancel throws it away.
              </span>
            </div>
          )}
        </WorkingCard>
      ) : run.status === "paused" ? (
        <>
          <h2 className="m-0 font-semibold text-lg">Paused</h2>
          <p className="m-0 text-muted-foreground">
            {run.stage || "Paused"}. Its place is kept, so it carries on from there. Chat and image
            making are free until you do.
          </p>
          <div className={actions}>
            <Button type="button" onClick={() => void t.resume(run.id)}>
              Carry on
            </Button>
            <Sure label="Discard" name="this run" onSure={() => void t.discard(run.id)} />
          </div>
        </>
      ) : run.status === "done" ? (
        <>
          <h2 className="m-0 font-semibold text-lg">
            {model ? `${model.name} is ready` : "Your model is ready"}
          </h2>
          {model ? (
            <p className="m-0">
              {model.card.family === "video" ? (
                <>
                  Write <code>{model.trigger_word}</code> in a video prompt and choose it under My
                  looks on a Video screen.
                </>
              ) : (
                <>
                  Write <code>{model.trigger_word}</code> in a prompt to draw it.
                </>
              )}
            </p>
          ) : null}
          {run.preview ? (
            <Notice tone="warn" title="This was a preview">
              Nothing was learnt. The pictures below only show the steps, and the file is not a
              trained model.
            </Notice>
          ) : null}
        </>
      ) : (
        <Notice
          tone={run.status === "cancelled" ? "info" : "error"}
          title={run.status === "cancelled" ? "Stopped" : "The teaching did not finish"}
        >
          {run.error ?? "Nothing was kept. The pictures are still there, so you can start again."}
        </Notice>
      )}

      {samples.length > 0 ? (
        <>
          <h3 className="m-0 font-semibold">
            {run.preview ? "Preview pictures" : "Pictures it made"}
          </h3>
          <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0 md:grid-cols-4">
            {samples.map((s) => (
              <li key={s.name} className="overflow-hidden rounded-lg border">
                <img src={s.src} alt={`Sample ${s.name}`} className="size-full object-cover" />
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {run.status === "done" && model && runs && model.card.family !== "video" ? (
        <>
          <CheckIt model={model} api={api} runs={runs} auto onSaved={() => void t.refresh()} />
          <TryIt model={model} runs={runs} />
        </>
      ) : null}

      {working ? null : (
        <div className={actions}>
          <Button type="button" onClick={() => void t.leave()}>
            {run.status === "done" ? "Done" : "Back to Train models"}
          </Button>
          {run.status === "done" && onOpenLibrary ? (
            <Button type="button" variant="outline" onClick={onOpenLibrary}>
              <FlaskConical className="size-4" aria-hidden="true" />
              Open the library
            </Button>
          ) : null}
          {run.status !== "done" && t.state.current ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                void t.openDataset((t.state.current as TrainDataset).id);
              }}
            >
              {t.state.current.family === "video" ? "Back to the set" : "Back to the pictures"}
            </Button>
          ) : null}
        </div>
      )}
    </section>
  );
}

export type { TrainState };
