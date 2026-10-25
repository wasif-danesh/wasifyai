"use client";

import type {
  Statement,
  TrainDataset,
  TrainKind,
  TrainPicture,
  TrainRun,
  TrainStatus,
  TrainedModel,
  TrainingApi,
} from "@wasifyai/client";
import { FlaskConical, Trash2, Upload } from "lucide-react";
import { type DragEvent, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { JobMeter, WorkingCard } from "../components/create";
import { Notice } from "../components/notice";
import type { ImageFlowApi } from "../hooks/use-image-flow";
import { actions, chips, eyebrow, field, fieldLabel, hint, panel } from "../styles";
import { CheckIt, EvaluationLine } from "./CheckIt";
import { SetupCard } from "./SetupCard";
import { TryIt } from "./TryIt";
import { useTrainingSetup } from "./use-setup";
import { type TrainState, useTraining } from "./use-training";

const INPUT =
  "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30";

const KIND_LABEL: Record<TrainKind, { title: string; note: string }> = {
  character: { title: "A character, pet, person or thing", note: "It appears in every picture." },
  style: { title: "A style", note: "The look of the pictures: how they are drawn or painted." },
  object: { title: "An idea or an object", note: "One kind of thing, shown in different places." },
};

/**
 * What can be taught, one card each (ADR-0073): the label says which kind of model it makes, the
 * headline says what the person gets. Only pictures are built; the others say when they are coming.
 */
const FAMILIES: {
  id: string;
  label: string;
  title: string;
  text: string;
  live?: boolean;
  soon?: string;
}[] = [
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
    title: "Teach my assistant to write like me",
    text: "From your own writing.",
    soon: "Coming next",
  },
  {
    id: "decision",
    label: "Decision model training",
    title: "Teach it to sort things",
    text: "From a spreadsheet of examples, for example spam or not spam.",
    soon: "Coming next",
  },
  {
    id: "video",
    label: "Video model training",
    title: "Make my own look or motion for video",
    text: "From short clips. Needs an NVIDIA graphics card for now.",
    soon: "Coming later",
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
  const showingRun = state.run !== null;
  return (
    <div className="mx-auto grid w-full max-w-5xl gap-5 p-[clamp(1rem,3vw,2rem)]">
      <header className="grid gap-1.5">
        <span className={eyebrow}>Train models</span>
        <h1 className="font-semibold text-step-2">
          {state.current || showingRun
            ? "Make my own character or style"
            : "Teach the app something of your own"}
        </h1>
        <p className="max-w-3xl text-muted-foreground">
          Add pictures and nothing else: the app describes them, suggests a magic word and teaches
          the image model.{" "}
          {place === "device"
            ? "It is learnt on this computer; your pictures are not sent anywhere."
            : "It is learnt on the service's graphics card."}
        </p>
      </header>

      {state.status?.preview ? (
        <Notice tone="info" title="A preview">
          Training runs every step and shows sample pictures, but it does not learn yet, so the
          models it makes are not real. The real trainer is coming.
        </Notice>
      ) : null}
      {notReady && setup.setup && setup.setup.plan.supported && !setup.setup.installed ? (
        <SetupCard
          setup={setup.setup}
          error={setup.error}
          onInstall={(bytes) => void setup.install(bytes)}
          onCancel={() => void setup.cancel()}
        />
      ) : notReady ? (
        <Notice tone="warn" title="Training is not ready">
          {setup.setup?.problem ?? state.status?.problem ?? "It could not be started."}
        </Notice>
      ) : null}
      {state.status?.fit?.verdict === "too_big" ? (
        <Notice tone="warn" title="Not enough memory to teach a model">
          {state.status.fit.reason}
        </Notice>
      ) : null}
      {state.error ? (
        <Notice tone="error" title="That did not work">
          {state.error}
        </Notice>
      ) : null}

      {state.loading ? (
        <output className="text-muted-foreground">Looking at training…</output>
      ) : showingRun && state.run ? (
        <RunView t={t} run={state.run} onOpenLibrary={onOpenLibrary} runs={runs} api={api} />
      ) : state.current ? (
        <MakeView t={t} status={state.status} />
      ) : (
        <Home t={t} runs={runs} setup={setup} api={api} />
      )}
    </div>
  );
}

// ---- the front door -----------------------------------------------------------------------------

function Home({
  t,
  runs,
  setup,
  api,
}: {
  t: Hook;
  runs?: ImageFlowApi;
  setup: ReturnType<typeof useTrainingSetup>;
  api: TrainingApi;
}) {
  const { state } = t;
  const ready = state.status?.ready === true;
  return (
    <>
      <section aria-label="What to teach" className="grid gap-3 md:grid-cols-2">
        {FAMILIES.map((f) => (
          <div
            key={f.id}
            className={cn(panel, "content-start", !f.live && "opacity-70")}
            aria-disabled={f.live ? undefined : "true"}
          >
            <span className={eyebrow}>{f.label}</span>
            <h2 className="m-0 font-semibold text-lg">{f.title}</h2>
            <p className="m-0 text-muted-foreground">{f.text}</p>
            {f.live ? (
              <div className={actions}>
                <Button
                  type="button"
                  disabled={!ready || state.busy !== null}
                  onClick={() => void t.newDataset()}
                >
                  Start
                </Button>
              </div>
            ) : (
              <span className="w-fit rounded-full border px-2.5 py-0.5 text-muted-foreground text-xs">
                {f.soon}
              </span>
            )}
          </div>
        ))}
      </section>

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
          <h2 className="m-0 font-semibold text-lg">Sets of pictures</h2>
          <ul className="m-0 grid list-none gap-2 p-0">
            {state.datasets.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-3 rounded-xl border p-3">
                <span className="min-w-0 flex-1">
                  <strong>{d.name || "Untitled set"}</strong>{" "}
                  <span className="text-muted-foreground">
                    · {KIND_LABEL[d.kind].title.toLowerCase()} · {d.pictures}{" "}
                    {d.pictures === 1 ? "picture" : "pictures"}
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
                <Sure
                  label="Remove"
                  name={d.name || "the set"}
                  onSure={() => void t.removeDataset(d.id)}
                />
              </li>
            ))}
          </ul>
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

      {setup.setup && (setup.setup.tool === "managed" || setup.setup.base === "managed") ? (
        <section aria-label="Training tools" className="grid gap-2">
          <h2 className="m-0 font-semibold text-lg">Training tools</h2>
          <p className={hint}>
            The trainer and the picture model it learns on are kept in the app's own folder.
            Removing them gives the space back; you can set them up again whenever you want to teach
            something. Your pictures and the models you taught are kept.
          </p>
          <div className={actions}>
            <Sure
              label="Remove"
              name="the trainer and the picture model"
              onSure={() => void setup.remove()}
            />
          </div>
        </section>
      ) : null}
    </>
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
      <p className="m-0 text-sm">
        Magic word: <code>{m.trigger_word}</code>
      </p>
      <p className={hint}>
        {KIND_LABEL[m.kind].title}, {m.card.dataset.pictures} pictures, {m.card.steps} steps,{" "}
        {m.card.base_title} · {m.card.licence}.{m.card.note ? ` ${m.card.note}` : ""}
      </p>
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
      {runs && !m.preview ? (
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

function MakeView({ t, status }: { t: Hook; status: TrainStatus | null }) {
  const d = t.state.current as TrainDataset;
  const [step, setStep] = useState<1 | 2>(1);
  const min = status?.min_pictures ?? 8;
  return (
    <>
      <nav aria-label="Steps" className="flex flex-wrap gap-2 text-sm">
        <span
          className={cn("rounded-full border px-3 py-1", step === 1 && "bg-accent font-medium")}
        >
          1 Add pictures
        </span>
        <span
          className={cn("rounded-full border px-3 py-1", step === 2 && "bg-accent font-medium")}
        >
          2 Check
        </span>
        <span className="rounded-full border px-3 py-1 text-muted-foreground">3 Teach</span>
      </nav>
      {step === 1 ? (
        <PicturesStep t={t} d={d} min={min} onNext={() => setStep(2)} />
      ) : (
        <CheckStep t={t} d={d} status={status} onBack={() => setStep(1)} />
      )}
      <div>
        <Button type="button" variant="ghost" size="sm" onClick={() => void t.leave()}>
          Back to Train models
        </Button>
      </div>
    </>
  );
}

function PicturesStep({
  t,
  d,
  min,
  onNext,
}: { t: Hook; d: TrainDataset; min: number; onNext: () => void }) {
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
    <section className={panel} aria-label="Add pictures">
      <section
        aria-label="Drop pictures here"
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
        <p className="m-0">Drop pictures here, or choose them.</p>
        <input
          id={pickerId}
          type="file"
          multiple
          accept="image/png,image/jpeg,image/webp"
          hidden
          aria-label="Choose pictures"
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
          {t.state.busy === "picture" ? "Adding…" : "Choose pictures"}
        </Button>
        <p className={hint}>
          15 to 25 good ones is plenty, and at least {min}. PNG, JPEG or WebP, under 20 MB each.
        </p>
      </section>

      {items.length > 0 ? (
        <>
          <p className="m-0" aria-live="polite">
            {items.length} {items.length === 1 ? "picture" : "pictures"}.
            {problems > 0 ? ` ${problems} with a problem.` : " All good."}
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
            Add at least {min} pictures ({min - items.length} more).
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
}: { t: Hook; d: TrainDataset; status: TrainStatus | null; onBack: () => void }) {
  const [own, setOwn] = useState("");
  const nameId = useId();
  const ownId = useId();
  const items = d.items ?? [];
  const suggestions = d.suggestions ?? [];
  const statements = status?.statements ?? ({} as Record<Statement, string>);
  const waiting = items.filter(
    (i) => i.caption_state === "none" || i.caption_state === "failed",
  ).length;
  const writing = d.writing || t.state.busy === "captions";
  const estimate = status?.estimates?.[d.kind] ?? "";
  const preflight = status?.preflight ?? null;
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
        <p className={hint}>{KIND_LABEL[d.kind].note}</p>
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
          When you write this word in a prompt, the app draws your {d.name || "character"}.
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

      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>Whose is it?</legend>
        <div className="grid gap-1.5">
          {(Object.keys(statements) as Statement[]).map((s) => (
            <label key={s} className="flex items-center gap-2">
              <input
                type="radio"
                name="rights"
                checked={d.rights === s}
                onChange={() => void t.change({ rights: s })}
              />
              {statements[s]}
            </label>
          ))}
        </div>
        <p className={hint}>
          A picture of a real person needs their agreement. Your answer is kept with the model.
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
          The app describes each picture in words. Read them and change any you like; the magic word
          goes first.
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
            preflight?.ok === false
          }
          onClick={() => void t.teach()}
        >
          Teach it
        </Button>
        <span className="text-muted-foreground">
          {d.missing ??
            `${estimate}. ${preflight?.pauses ?? "Chat and image making pause while it learns."}`}
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
          {run.preview ? null : (
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
              Write <code>{model.trigger_word}</code> in a prompt to draw it.
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

      {run.status === "done" && model && runs ? (
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
              Back to the pictures
            </Button>
          ) : null}
        </div>
      )}
    </section>
  );
}

export type { TrainState };
