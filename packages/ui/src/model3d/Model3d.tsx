"use client";

import {
  type Detail,
  type Model3d as Model,
  type Model3dApi,
  type PictureCheck,
  gigabytes,
  minutes,
} from "@wasifyai/client";
import { Library, Save, Trash2, Upload } from "lucide-react";
import { type DragEvent, useEffect, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { JobMeter, WorkingCard } from "../components/create";
import { Notice } from "../components/notice";
import { Spinner } from "../components/spinner";
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
  return (
    <TopBarSlot>
      {choices ? (
        // the model button is at the top of the screen, as on the chat and image screens (ADR-0086)
        <PageHeader className="flex h-14 shrink-0 items-center gap-4 border-b px-6 pt-1">
          <div className="flex items-center gap-2 ps-2 text-sm">
            <ModelSelect group="three_d" api={choices} />
          </div>
        </PageHeader>
      ) : null}
      <div className="mx-auto grid w-full max-w-5xl gap-5 p-[clamp(1rem,3vw,2rem)]">
        <header className="grid gap-1.5">
          <span className={eyebrow}>Experimental</span>
          <h1 className="font-semibold text-step-2">Make a 3D model</h1>
          <p className="max-w-3xl text-muted-foreground">
            Turn a picture of one object into a 3D model you can turn around and save as a file. It
            is{" "}
            {place === "device"
              ? "made on this computer; nothing is sent anywhere."
              : "made on the service's graphics card. The picture is sent there and deleted when the model is made."}
          </p>
        </header>

        {state.error ? (
          <Notice tone="error" title="That did not work">
            {state.error}
          </Notice>
        ) : null}

        {state.loading ? (
          <output className="text-muted-foreground">Looking at 3D…</output>
        ) : !state.component?.installed && picking ? (
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
        ) : !state.component?.installed ? (
          <SetupCard
            component={state.component}
            onInstall={(bytes) => void m.install(bytes)}
            onCancel={() => void m.cancelInstall()}
            onRetry={() => void m.refresh()}
          />
        ) : (
          <>
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
            {state.model ? (
              <ModelStep
                m={m}
                canSave={canSave}
                downloadHref={downloadHref}
                api={api}
                onOpenLibrary={onOpenLibrary}
              />
            ) : state.input ? (
              <CheckStep m={m} />
            ) : (
              <StartStep m={m} images={images} />
            )}
            <ModelsRow m={m} />
            <p className={hint}>
              {state.component.about.built_with}. {state.component.about.licence}
            </p>
          </>
        )}
      </div>
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
              {gigabytes(p.bytes)} · {p.licence} · from {p.source}
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
    <section className={panel} aria-label="Start from">
      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>Start from</legend>
        <div className={chips}>
          <Chip aria-pressed={from === "picture"} onClick={() => setFrom("picture")}>
            A picture
          </Chip>
          <Chip aria-pressed={from === "words"} onClick={() => setFrom("words")} disabled={!images}>
            Words
          </Chip>
          <Chip aria-pressed="false" disabled title="Four photos around the object come later">
            Four photos (soon)
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
            "grid justify-items-center gap-2 rounded-xl border border-dashed p-8 text-center",
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

function CheckStep({ m }: { m: Hook }) {
  const { input, shown } = m.state;
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState<Detail>("standard");
  const [rights, setRights] = useState(false);
  const titleId = useId();
  const rightsId = useId();
  if (!input) return null;
  const checking = input.status === "checking";
  const tooBig = m.state.status?.fit?.verdict === "too_big";
  const busy = Boolean(m.state.status?.busy);
  const canMake = input.can_go_on && rights && !tooBig && !busy && m.state.busyWith !== "make";

  return (
    <section className={panel} aria-label="Check the picture">
      <h2 className="font-semibold text-lg">Check the picture</h2>
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
        <>
          <ul aria-label="What was found" className="grid gap-1.5">
            {input.checks.map((c) => (
              <li key={c.code} className="flex gap-2.5">
                <span className={cn("w-4 font-bold", TONE[c.level])} aria-hidden="true">
                  {MARK[c.level]}
                </span>
                <span>{c.message}</span>
              </li>
            ))}
          </ul>

          {input.can_go_on ? (
            <form
              className="grid gap-4"
              aria-label="Make the model"
              onSubmit={(e) => {
                e.preventDefault();
                if (canMake) {
                  void m.make({
                    title: title.trim(),
                    prompt: "",
                    detail,
                    rights,
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
                  value={title}
                  maxLength={200}
                  placeholder="Frog mug"
                  onChange={(e) => setTitle(e.target.value)}
                />
              </div>
              <fieldset className={cn(field, "m-0 border-0 p-0")}>
                <legend className={cn(fieldLabel, "mb-1.5")}>Detail</legend>
                <div className={chips}>
                  {DETAILS.map((d) => (
                    <Chip key={d.id} aria-pressed={detail === d.id} onClick={() => setDetail(d.id)}>
                      {d.label}
                    </Chip>
                  ))}
                </div>
                <p className={hint}>{DETAILS.find((d) => d.id === detail)?.note}</p>
              </fieldset>
              <div className="flex items-start gap-2.5">
                <input
                  id={rightsId}
                  type="checkbox"
                  className="mt-1 size-4"
                  checked={rights}
                  onChange={(e) => setRights(e.target.checked)}
                />
                <label htmlFor={rightsId}>
                  I may use this picture, and it is not a photo of a real person who has not agreed.
                </label>
              </div>
              <p className={hint}>
                It takes about 5 to 25 minutes, depending on how detailed the object is, and about
                19 GB of memory. You can leave this screen while it works.
              </p>
              <div className={actions}>
                <Button type="submit" size="lg" disabled={!canMake}>
                  Make the 3D model
                </Button>
                <Button type="button" variant="ghost" onClick={() => void m.discardPicture()}>
                  Use another picture
                </Button>
              </div>
              {busy ? (
                <p className={hint}>A 3D model is being made. Wait for it to finish.</p>
              ) : null}
            </form>
          ) : (
            <div className={actions}>
              <Button type="button" onClick={() => void m.discardPicture()}>
                Use another picture
              </Button>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}

// ---- 3 and 4: being made, and made ---------------------------------------------------------------

function ModelStep({
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
  const [name, setName] = useState<string | null>(null);
  const nameId = useId();
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

  if (model.status === "working") {
    const pct = Math.round(model.progress * 100);
    return (
      <WorkingCard label="Making your 3D model" onCancel={() => void m.cancel()}>
        <JobMeter
          title={model.stage || "Starting"}
          text={model.progress > 0 ? `${pct}%` : "Starting"}
          value={model.progress > 0 ? model.progress : undefined}
          label="3D progress"
        />
        <p className={hint}>
          This takes about 5 to 25 minutes. You can leave this screen: it keeps working, and the
          model will be in Your 3D models.
        </p>
      </WorkingCard>
    );
  }

  if (model.status === "failed" || model.status === "cancelled") {
    return (
      <section className={panel} aria-label="The 3D model">
        <Notice
          tone={model.status === "cancelled" ? "info" : "error"}
          title={model.status === "cancelled" ? "Stopped" : "The 3D model could not be made"}
        >
          {model.error ?? "It did not finish."}
        </Notice>
        <div className={actions}>
          {model.input_id ? (
            <Button type="button" onClick={() => void m.again()}>
              Try again
            </Button>
          ) : null}
          <Button type="button" variant="outline" onClick={() => m.startOver()}>
            Start over
          </Button>
          <Button type="button" variant="ghost" onClick={() => void m.remove(model.id)}>
            <Trash2 className="size-4" /> Delete
          </Button>
        </div>
      </section>
    );
  }

  return (
    <section className={panel} aria-label="Your 3D model">
      <Notice tone="ok" title="Your 3D model is ready">
        {model.elapsed_s ? `It took ${minutes(model.elapsed_s)}. ` : ""}It is saved in Your 3D
        models. Drag to turn it, scroll to zoom.
      </Notice>
      {glb ? (
        <ModelViewer src={glb} label={`3D model: ${model.title}`} />
      ) : (
        <output className="text-muted-foreground">Opening your model…</output>
      )}
      <div className="grid gap-1.5">
        <label className={fieldLabel} htmlFor={nameId}>
          Name
        </label>
        <div className="flex flex-wrap gap-2">
          <input
            id={nameId}
            className={cn(INPUT, "max-w-sm")}
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
      <div className={actions}>
        {canSave ? (
          <Button type="button" onClick={() => void saveCopy()}>
            <Save className="size-4" /> Save a copy (GLB)
          </Button>
        ) : downloadHref ? (
          <Button asChild>
            <a href={downloadHref({ id: model.id, title: model.title })} download>
              <Save className="size-4" /> Download (GLB)
            </a>
          </Button>
        ) : null}
        {model.input_id ? (
          <Button type="button" variant="outline" onClick={() => void m.again()}>
            Make it again
          </Button>
        ) : null}
        <Button type="button" variant="outline" onClick={() => m.startOver()}>
          Make another
        </Button>
        {onOpenLibrary ? (
          <Button type="button" variant="ghost" onClick={onOpenLibrary}>
            <Library className="size-4" /> Library
          </Button>
        ) : null}
        {confirmDelete ? (
          <>
            <Button type="button" variant="destructive" onClick={() => void m.remove(model.id)}>
              Delete it for good
            </Button>
            <Button type="button" variant="ghost" onClick={() => setConfirmDelete(false)}>
              Keep it
            </Button>
          </>
        ) : (
          <Button type="button" variant="ghost" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="size-4" /> Delete
          </Button>
        )}
      </div>
      {saved ? <output className="text-sm">{saved}</output> : null}
      {problem ? (
        <Notice tone="error" title="That did not work">
          {problem}
        </Notice>
      ) : null}
    </section>
  );
}

// ---- the models already made -------------------------------------------------------------------

function ModelsRow({ m }: { m: Hook }) {
  const { models, thumbs, model } = m.state;
  const shown = models.filter((x) => x.status === "done" || x.status === "working");
  if (shown.length === 0) return null;
  return (
    <section className="grid gap-2" aria-label="Your 3D models">
      <h2 className="font-semibold text-lg">Your 3D models</h2>
      <ul className="flex flex-wrap gap-3">
        {shown.map((x) => (
          <li key={x.id}>
            <button
              type="button"
              aria-current={model?.id === x.id ? "true" : undefined}
              onClick={() => void m.open(x.id)}
              className="grid w-32 gap-1 rounded-lg border p-1.5 text-start hover:bg-accent aria-[current=true]:bg-accent"
            >
              <span className="grid aspect-square place-items-center overflow-hidden rounded-md bg-muted">
                {thumbs[x.id] ? (
                  <img src={thumbs[x.id]} alt="" className="size-full object-cover" />
                ) : (
                  <span className={hint}>{x.status === "working" ? "Making…" : "3D"}</span>
                )}
              </span>
              <span className="truncate text-sm">{x.title}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
