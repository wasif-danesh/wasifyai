"use client";

import {
  type Detail,
  type Model3d as Model,
  type Model3dApi,
  type PictureCheck,
  gigabytes,
  minutes,
} from "@wasifyai/client";
import { Box, Library, Save, Trash2, Upload } from "lucide-react";
import { type DragEvent, useEffect, useId, useState } from "react";
import { cn } from "../cn";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { JobMeter, WorkingCard } from "../components/create";
import { ConfirmDialog } from "../components/dialog";
import { FRAME, MakeScreen } from "../components/make-screen";
import { Notice } from "../components/notice";
import { RecentStrip } from "../components/recent-strip";
import { Spinner } from "../components/spinner";
import { Stage } from "../components/stage";
import { Stepper } from "../components/stepper";
import { ModelSelect, useChoicesFor, useChoicesVersion } from "../models";
import { fileNameFor, savedText, useSaveCopy } from "../save";
import { actions, chips, eyebrow, field, fieldLabel, hint, panel } from "../styles";
import { PageHeader, TopBarSlot } from "../window-bar";
import { type CandidateApi, Candidates } from "./Candidates";
import { ModelViewer } from "./ModelViewer";
import { useModel3d } from "./use-model3d";

const INPUT =
  "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30";
// a grey chequerboard, so a see-through cut-out can be seen to be see-through
const CHEQUER =
  "repeating-conic-gradient(color-mix(in srgb, currentColor 25%, transparent) 0% 25%, transparent 0% 50%) 50% / 20px 20px";

const DETAILS: { id: Detail; label: string; note: string }[] = [
  {
    id: "light",
    label: "Light",
    note: "A small texture (1024). The model itself is the same size.",
  },
  { id: "standard", label: "Standard", note: "A medium texture (2048). A good balance." },
  {
    id: "detailed",
    label: "Detailed",
    note: "The sharpest texture (4096). Takes a little longer.",
  },
];

export type Model3dProps = {
  api: Model3dApi;
  /** To make pictures from words: the image engine. Without it only a picture can be used. */
  images?: CandidateApi;
  /** "Save a copy" of a finished model (the desktop app). */
  canSave?: boolean;
  /** Where a finished model can be downloaded from (the web app): "Download" is offered when given. */
  downloadHref?: (model: { id: string; title: string }) => string;
  /** Where the work is done: on this computer (the desktop) or on a service's worker (the web). */
  place?: "device" | "service";
  onOpenLibrary?: () => void;
};

/** Experimental: make a 3D model from a picture, or from words through a picture you choose. */
export function Model3d({
  api,
  images,
  canSave = false,
  downloadHref,
  place = "device",
  onOpenLibrary,
}: Model3dProps) {
  const m = useModel3d(api);
  const { state } = m;
  // in the app window the same button as every other model: its dialog says what 3D needs and sets it up (ADR-0086)
  const choices = useChoicesFor("three_d");
  const version = useChoicesVersion();
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    if (version > 0) void m.refresh();
  }, [version]);
  const picking =
    choices !== null &&
    state.component !== null &&
    state.component.plan.supported &&
    state.component.progress.state !== "installing";
  const step = state.model ? 2 : state.input ? 1 : 0;
  const formId = useId();
  // the check's choices live here: the form is in the ask column and its button at the bottom of it
  const [check, setCheck] = useState<Check>(NEW_CHECK);
  const inputId = state.input?.id;
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new picture starts a new check
  useEffect(() => setCheck(NEW_CHECK), [inputId]);
  const lead =
    place === "device"
      ? "Turn a picture of one object into a 3D model you can turn around and save as a file. It is made on this computer; nothing is sent anywhere."
      : "Turn a picture of one object into a 3D model you can turn around and save as a file. It is made on the service's graphics card. The picture is sent there and deleted when the model is made.";
  return (
    <TopBarSlot>
      {choices ? (
        // the model button is at the top of the screen, as on the chat and image screens (ADR-0086)
        <PageHeader className="flex h-14 shrink-0 items-center gap-4 border-b px-6 pt-1">
          <div className="flex min-w-0 items-center gap-2 ps-2 text-sm">
            <ModelSelect group="three_d" api={choices} />
          </div>
        </PageHeader>
      ) : null}
      {state.loading || !state.component?.installed ? (
        <div className="mx-auto grid w-full max-w-5xl gap-5 p-[clamp(1rem,3vw,2rem)]">
          <header className="grid gap-1.5">
            <h1 className="font-semibold text-step-2">Make a 3D model</h1>
            <p className="max-w-3xl text-muted-foreground">{lead}</p>
          </header>
          {state.error ? (
            <Notice tone="error" title="That did not work">
              {state.error}
            </Notice>
          ) : null}
          {state.loading ? (
            <output className="text-muted-foreground">Looking at 3D…</output>
          ) : picking ? (
            <section
              aria-label="Choose a 3D model"
              className="grid gap-3 rounded-2xl border bg-card p-5"
            >
              <h2 className="m-0 font-semibold text-lg">Choose a 3D model</h2>
              <p className="m-0 text-muted-foreground">
                Making a 3D model needs a model on this computer. Select it to see what it needs and
                download it.
              </p>
              <p className="m-0 text-muted-foreground text-sm">Use the model button at the top.</p>
            </section>
          ) : (
            <SetupCard
              component={state.component}
              onInstall={(bytes) => void m.install(bytes)}
              onCancel={() => void m.cancelInstall()}
              onRetry={() => void m.refresh()}
            />
          )}
        </div>
      ) : (
        // the make frame (ADR-0093 U10): the steps and their fields on the left, the picture, the progress and
        // the model on the stage, the models already made under it; it fills the window under the bar
        <div data-workspace className={FRAME}>
          <MakeScreen
            title="Make a 3D model"
            lead={<>Experimental. {lead}</>}
            ask={
              <>
                <Stepper steps={["Picture", "Check", "Make"]} current={step} />
                {state.error ? (
                  <Notice tone="error" title="That did not work">
                    {state.error}
                  </Notice>
                ) : null}
                {state.status && !state.status.ready ? (
                  <Notice tone="warn" title="3D is not ready">
                    {state.status.problem ?? "It could not be started."}
                  </Notice>
                ) : null}
                {state.status?.fit?.verdict === "tight" ? (
                  <Notice tone="warn" title="Memory is tight">
                    {state.status.fit.reason}
                  </Notice>
                ) : null}
                {state.status?.fit?.verdict === "too_big" ? (
                  <Notice tone="warn" title="Not enough memory for a 3D model">
                    {state.status.fit.reason}
                  </Notice>
                ) : null}
                {step === 0 ? (
                  <StartStep m={m} images={images} />
                ) : step === 1 ? (
                  <CheckAsk m={m} form={formId} check={check} setCheck={setCheck} />
                ) : (
                  <ModelAbout m={m} />
                )}
                <p className={hint}>{state.component.about.built_with}.</p>
              </>
            }
            action={
              step === 0 ? (
                <p className={hint}>Add a picture of one object to start.</p>
              ) : step === 1 ? (
                <CheckAction m={m} form={formId} check={check} />
              ) : (
                <ModelAction m={m} />
              )
            }
            stage={
              step === 0 ? (
                <Stage
                  state={{
                    kind: "empty",
                    icon: Box,
                    title: "Your 3D model appears here",
                    text: "Start from a picture of one object, or from words.",
                  }}
                />
              ) : step === 1 ? (
                <CheckStage m={m} />
              ) : (
                <ModelStage
                  m={m}
                  canSave={canSave}
                  downloadHref={downloadHref}
                  api={api}
                  onOpenLibrary={onOpenLibrary}
                />
              )
            }
            recent={<ModelsStrip m={m} onSeeAll={onOpenLibrary} />}
          />
        </div>
      )}
    </TopBarSlot>
  );
}

type Hook = ReturnType<typeof useModel3d>;

// ---- setting it up ------------------------------------------------------------------------------

function SetupCard({
  component,
  onInstall,
  onCancel,
  onRetry,
}: {
  component: Hook["state"]["component"];
  onInstall: (bytes: number) => void;
  onCancel: () => void;
  onRetry: () => void;
}) {
  if (!component) {
    return (
      <Notice
        tone="error"
        title="3D could not be reached"
        actions={<Button onClick={onRetry}>Try again</Button>}
      >
        The engine did not answer. Try again in a moment.
      </Notice>
    );
  }
  const { plan, progress } = component;
  if (!plan.supported) {
    return (
      <Notice tone="info" title="Not on this computer yet">
        3D models were measured on Apple-silicon Macs and are not offered on other computers yet.
      </Notice>
    );
  }
  const installing = progress.state === "installing";
  const value = progress.total_bytes > 0 ? progress.done_bytes / progress.total_bytes : undefined;
  return (
    <section className={panel} aria-label="Set up 3D">
      <h2 className="font-semibold text-lg">Set up 3D</h2>
      <p className="text-muted-foreground">
        It needs an engine and its models, which are not in the app. They are downloaded once, every
        file checked, and kept in the app's own folder. Nothing else on your computer is changed.
      </p>
      <ul className="grid gap-1.5">
        {plan.parts.map((p) => (
          <li key={p.name} className="flex flex-wrap justify-between gap-x-4">
            <span>
              <strong>{p.name}</strong> <span className="text-muted-foreground">{p.version}</span>
            </span>
            <span className="text-muted-foreground tabular-nums">
              {gigabytes(p.bytes)} · from {p.source}
            </span>
          </li>
        ))}
      </ul>
      <p className={hint}>
        Built with DINOv3. The models need about 19 GB of free memory while they work, and a model
        takes about 5 to 25 minutes.
      </p>
      {component.fit?.verdict === "too_big" ? (
        <Notice tone="warn" title="Not enough memory">
          {component.fit.reason}
        </Notice>
      ) : null}
      {installing ? (
        <WorkingCard label={progress.message || "Setting up"} onCancel={onCancel}>
          <JobMeter
            title="Setting up 3D"
            text={value === undefined ? "Starting" : `${Math.round(value * 100)}%`}
            value={value}
            label="Setup progress"
          />
        </WorkingCard>
      ) : (
        <div className={actions}>
          <Button type="button" size="lg" onClick={() => onInstall(plan.bytes)}>
            Download and set up ({gigabytes(plan.bytes)})
          </Button>
          <span className="text-muted-foreground">
            It continues where it stopped if it is interrupted.
          </span>
        </div>
      )}
      {progress.state === "failed" ? (
        <Notice tone="error" title="Setting up did not finish">
          {progress.message}
        </Notice>
      ) : null}
    </section>
  );
}

// ---- 1: start from a picture or from words -------------------------------------------------------

function StartStep({ m, images }: { m: Hook; images?: CandidateApi }) {
  const [from, setFrom] = useState<"picture" | "words">("picture");
  const [words, setWords] = useState("");
  const [over, setOver] = useState(false);
  const pickerId = useId();
  const wordsId = useId();
  const busy = m.state.busyWith === "picture";

  const take = (file: File | undefined) => {
    if (file) void m.addPicture(file, file.name);
  };
  const drop = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    setOver(false);
    take(e.dataTransfer.files[0]);
  };

  return (
    <section className="grid gap-4" aria-label="Start from">
      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>Start from</legend>
        <div className={chips}>
          <Chip aria-pressed={from === "picture"} onClick={() => setFrom("picture")}>
            A picture
          </Chip>
          <Chip aria-pressed={from === "words"} onClick={() => setFrom("words")} disabled={!images}>
            Words
          </Chip>
        </div>
      </fieldset>
      {from === "picture" ? (
        <section
          aria-label="Add a picture"
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={drop}
          className={cn(
            "grid justify-items-center gap-2 rounded-xl border border-dashed p-6 text-center",
            over && "border-ring bg-accent",
          )}
        >
          <Upload className="size-6 text-muted-foreground" aria-hidden="true" />
          <p>Drop a picture here, or choose one.</p>
          <input
            id={pickerId}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            aria-label="Choose a picture"
            onChange={(e) => {
              take(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => document.getElementById(pickerId)?.click()}
          >
            Choose a picture
          </Button>
          <p className={hint}>
            One object, straight on at eye level, on a plain background works best. PNG, JPEG or
            WebP, under 20 MB.
          </p>
        </section>
      ) : images ? (
        <div className="grid gap-3">
          <div className={field}>
            <label className={fieldLabel} htmlFor={wordsId}>
              Describe the object
            </label>
            <input
              id={wordsId}
              className={INPUT}
              value={words}
              maxLength={300}
              placeholder="A ceramic mug shaped like a cartoon frog, green glaze"
              onChange={(e) => setWords(e.target.value)}
            />
            <p className={hint}>
              The app adds "single object, plain background, front view" so the model comes out
              well.
            </p>
          </div>
          <Candidates
            api={images}
            words={words}
            busy={busy}
            onPick={(picture, name) => void m.addPicture(picture, name)}
          />
        </div>
      ) : null}
    </section>
  );
}

// ---- 2: look at the picture and choose ---------------------------------------------------------

const MARK: Record<PictureCheck["level"], string> = { ok: "✓", warn: "!", stop: "×" };
const TONE: Record<PictureCheck["level"], string> = {
  ok: "text-ok",
  warn: "text-warn",
  stop: "text-destructive",
};

type Check = { title: string; detail: Detail };
const NEW_CHECK: Check = { title: "", detail: "standard" };

function canMakeNow(m: Hook, check: Check) {
  const { input, status, busyWith } = m.state;
  return Boolean(
    input?.can_go_on && status?.fit?.verdict !== "too_big" && !status?.busy && busyWith !== "make",
  );
}

/** The picture and its cut-out, side by side on the stage, while it is checked and once it is. */
function CheckStage({ m }: { m: Hook }) {
  const { input, shown } = m.state;
  if (!input) return null;
  const checking = input.status === "checking";
  return (
    <div className="grid w-full max-w-3xl gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <figure className="m-0 grid gap-1.5">
          <div className="grid aspect-square place-items-center overflow-hidden rounded-xl border bg-muted">
            {shown.picture ? (
              <img
                src={shown.picture}
                alt="The original, as you gave it"
                className="size-full object-contain"
              />
            ) : (
              <span className={hint}>{input.name || "Your picture"}</span>
            )}
          </div>
          <figcaption className={hint}>Your picture</figcaption>
        </figure>
        <figure className="m-0 grid gap-1.5">
          <div
            className="grid aspect-square place-items-center overflow-hidden rounded-xl border"
            style={shown.cutout ? { background: CHEQUER } : undefined}
          >
            {shown.cutout ? (
              <img
                src={shown.cutout}
                alt="The object cut out"
                className="size-full object-contain"
              />
            ) : checking ? (
              <output className={cn(hint, "flex items-center gap-2.5")}>
                <Spinner />
                {input.stage || "Cutting out the object"}…
              </output>
            ) : null}
          </div>
          <figcaption className={hint}>Is this the object? (cut out)</figcaption>
        </figure>
      </div>
      {checking ? (
        <JobMeter
          title={input.stage || "Cutting out the object"}
          text="This can take a minute"
          label="Checking the picture"
        />
      ) : null}
    </div>
  );
}

/** What was found in the picture, and the name and detail for the model. */
function CheckAsk({
  m,
  form,
  check,
  setCheck,
}: {
  m: Hook;
  form: string;
  check: Check;
  setCheck: (c: Check) => void;
}) {
  const { input } = m.state;
  const titleId = useId();
  if (!input) return null;
  return (
    <section className="grid gap-4" aria-label="Check the picture">
      <h2 className="m-0 font-semibold text-base">Check the picture</h2>
      {input.status === "checking" ? (
        <p className={hint}>The object is being cut out of the picture. This can take a minute.</p>
      ) : null}
      {input.status === "failed" ? (
        <Notice
          tone="error"
          title="That picture could not be used"
          actions={
            <Button type="button" onClick={() => void m.discardPicture()}>
              Try another picture
            </Button>
          }
        >
          {input.error ?? "It did not work."}
        </Notice>
      ) : null}
      {input.status === "ready" ? (
        <ul aria-label="What was found" className="m-0 grid list-none gap-1.5 p-0">
          {input.checks.map((c) => (
            <li key={c.code} className="flex gap-2.5">
              <span className={cn("w-4 font-bold", TONE[c.level])} aria-hidden="true">
                {MARK[c.level]}
              </span>
              <span>{c.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {input.status === "ready" && input.can_go_on ? (
        <form
          id={form}
          className="grid gap-4"
          aria-label="Make the model"
          onSubmit={(e) => {
            e.preventDefault();
            if (canMakeNow(m, check)) {
              void m.make({
                title: check.title.trim(),
                prompt: "",
                detail: check.detail,
              });
            }
          }}
        >
          <div className={field}>
            <label className={fieldLabel} htmlFor={titleId}>
              Name <span className="font-normal text-muted-foreground">(optional)</span>
            </label>
            <input
              id={titleId}
              className={INPUT}
              value={check.title}
              maxLength={200}
              placeholder="Frog mug"
              onChange={(e) => setCheck({ ...check, title: e.target.value })}
            />
          </div>
          <fieldset className={cn(field, "m-0 border-0 p-0")}>
            <legend className={cn(fieldLabel, "mb-1.5")}>Detail</legend>
            <div className={chips}>
              {DETAILS.map((d) => (
                <Chip
                  key={d.id}
                  aria-pressed={check.detail === d.id}
                  onClick={() => setCheck({ ...check, detail: d.id })}
                >
                  {d.label}
                </Chip>
              ))}
            </div>
            <p className={hint}>{DETAILS.find((d) => d.id === check.detail)?.note}</p>
          </fieldset>
          <p className={hint}>
            It takes about 5 to 25 minutes, depending on how detailed the object is, and about 19 GB
            of memory. You can leave this screen while it works.
          </p>
        </form>
      ) : null}
    </section>
  );
}

/** The step's buttons, always in view at the bottom of the ask column. */
function CheckAction({ m, form, check }: { m: Hook; form: string; check: Check }) {
  const { input } = m.state;
  if (!input) return null;
  const going = input.status === "ready" && input.can_go_on;
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {going ? (
          <Button type="submit" form={form} size="lg" disabled={!canMakeNow(m, check)}>
            Make the 3D model
          </Button>
        ) : null}
        {input.status === "failed" ? null : (
          <Button
            type="button"
            variant={going ? "ghost" : "default"}
            onClick={() => void m.discardPicture()}
          >
            Use another picture
          </Button>
        )}
      </div>
      {going && m.state.status?.busy ? (
        <p className={hint}>A 3D model is being made. Wait for it to finish.</p>
      ) : null}
    </div>
  );
}

// ---- 3 and 4: being made, and made ---------------------------------------------------------------

/** The model's name, renamed here, and what kind of file it is. */
function ModelAbout({ m }: { m: Hook }) {
  const { model } = m.state;
  const [name, setName] = useState<string | null>(null);
  const nameId = useId();
  if (!model) return null;
  if (model.status !== "done") {
    return (
      <p className={hint}>
        {model.status === "working"
          ? "This takes about 5 to 25 minutes. You can leave this screen: it keeps working, and the model will be in Your 3D models."
          : "Nothing was kept. Try again, or start over with another picture."}
      </p>
    );
  }
  return (
    <section className="grid gap-4" aria-label="About the model">
      <div className="grid gap-1.5">
        <label className={fieldLabel} htmlFor={nameId}>
          Name
        </label>
        <div className="flex flex-wrap gap-2">
          <input
            id={nameId}
            className={cn(INPUT, "min-w-0 flex-1")}
            value={name ?? model.title}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            disabled={name === null || name.trim() === "" || name === model.title}
            onClick={() => {
              void m.rename(name ?? "");
              setName(null);
            }}
          >
            Rename
          </Button>
        </div>
      </div>
      <p className={hint}>
        About a million triangles, a file of {model.glb_bytes ? gigabytes(model.glb_bytes) : "?"}.
        It is not watertight, so it suits viewing and rendering better than 3D printing.
      </p>
    </section>
  );
}

function ModelAction({ m }: { m: Hook }) {
  const { model } = m.state;
  if (!model || model.status === "working") {
    return <p className={hint}>It keeps working if you leave this screen.</p>;
  }
  return (
    <Button type="button" size="lg" variant="outline" onClick={() => m.startOver()}>
      Make another
    </Button>
  );
}

function ModelStage({
  m,
  api,
  canSave,
  downloadHref,
  onOpenLibrary,
}: {
  m: Hook;
  api: Model3dApi;
  canSave: boolean;
  downloadHref?: Model3dProps["downloadHref"];
  onOpenLibrary?: () => void;
}) {
  const { model, glb } = m.state;
  const [saved, setSaved] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const save = useSaveCopy();
  if (!model) return null;

  async function saveCopy() {
    setProblem(null);
    try {
      const m3 = model as Model;
      const done = await save({
        name: fileNameFor(m3.title, "glb", "model"),
        copy: (path) => api.exportCopy(m3.id, path),
      });
      if (done) setSaved(savedText(done));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The model could not be saved.");
    }
  }

  const ask = confirmDelete ? (
    <ConfirmDialog
      title="Delete this 3D model?"
      message={`“${model.title}” will be deleted, with its file.`}
      confirmLabel="Delete it for good"
      onConfirm={() => {
        setConfirmDelete(false);
        void m.remove(model.id);
      }}
      onCancel={() => setConfirmDelete(false)}
    />
  ) : null;

  if (model.status === "working") {
    return (
      <Stage
        state={{
          kind: "working",
          label: "Making your 3D model",
          text: model.stage || "Starting",
          value: model.progress > 0 ? model.progress : undefined,
          onStop: () => void m.cancel(),
        }}
      />
    );
  }

  if (model.status === "failed" || model.status === "cancelled") {
    return (
      <div className="grid w-full justify-items-center gap-3">
        <Stage
          state={{
            kind: "error",
            title: model.status === "cancelled" ? "Stopped" : "The 3D model could not be made",
            message: model.error ?? "It did not finish.",
            onRetry: model.input_id ? () => void m.again() : undefined,
            onReset: () => m.startOver(),
          }}
        />
        <Button type="button" variant="ghost" onClick={() => setConfirmDelete(true)}>
          <Trash2 className="size-4" /> Delete
        </Button>
        {ask}
      </div>
    );
  }

  const actions: Action[] = [
    ...(canSave
      ? [
          {
            label: "Save a copy (GLB)",
            onSelect: () => void saveCopy(),
            icon: <Save aria-hidden="true" />,
          },
        ]
      : downloadHref
        ? [
            {
              label: "Download (GLB)",
              href: downloadHref({ id: model.id, title: model.title }),
              download: true,
              icon: <Save aria-hidden="true" />,
            },
          ]
        : []),
    ...(model.input_id ? [{ label: "Make it again", onSelect: () => void m.again() }] : []),
    ...(onOpenLibrary
      ? [{ label: "Library", onSelect: onOpenLibrary, icon: <Library aria-hidden="true" /> }]
      : []),
    {
      label: "Delete",
      onSelect: () => setConfirmDelete(true),
      icon: <Trash2 aria-hidden="true" />,
      destructive: true,
    },
  ];
  return (
    <>
      <Stage
        state={{
          kind: "result",
          children: glb ? (
            <ModelViewer src={glb} label={`3D model: ${model.title}`} />
          ) : (
            <output className="text-muted-foreground">Opening your model…</output>
          ),
          caption: (
            <span className="grid gap-1">
              <span>
                <strong className="font-medium text-foreground">Your 3D model is ready</strong>
                {" · "}
                {model.elapsed_s ? `It took ${minutes(model.elapsed_s)}. ` : ""}Drag to turn it,
                scroll to zoom.
              </span>
              {saved ? <output>{saved}</output> : null}
              {problem ? <output className="text-destructive">{problem}</output> : null}
            </span>
          ),
          actions,
        }}
      />
      {ask}
    </>
  );
}

// ---- the models already made -------------------------------------------------------------------

function ModelsStrip({ m, onSeeAll }: { m: Hook; onSeeAll?: () => void }) {
  const { models, thumbs, model } = m.state;
  const shown = models.filter((x) => x.status === "done" || x.status === "working");
  return (
    <RecentStrip
      title="Your 3D models"
      empty="Nothing made yet. Your 3D models will show up here."
      onSeeAll={onSeeAll}
      items={shown.map((x) => ({
        id: x.id,
        label: x.title,
        current: model?.id === x.id,
        onOpen: () => void m.open(x.id),
        cover: thumbs[x.id] ? (
          <img src={thumbs[x.id]} alt="" />
        ) : (
          <span className="grid place-items-center text-muted-foreground text-xs">
            {x.status === "working" ? "Making…" : "3D"}
          </span>
        ),
      }))}
    />
  );
}
