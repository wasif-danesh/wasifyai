"use client";

import {
  type BuilderCheck,
  type BuilderFormat,
  type BuilderProject,
  type FieldInfo,
  type TemplateCatalogue,
  type TemplateInfo,
  type VideoBuilderApi,
  type VideosApi,
  megabytes,
} from "@wasifyai/client";
import { Clapperboard, Library, Plus, Save, Trash2, Undo2, X } from "lucide-react";
import { type ReactNode, useEffect, useId, useState } from "react";
import { cn } from "../cn";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { JobMeter, WorkingCard } from "../components/create";
import { FRAME, MakeScreen } from "../components/make-screen";
import { Notice } from "../components/notice";
import { Stage } from "../components/stage";
import { extensionOf, fileNameFor, savedText, useSaveCopy } from "../save";
import { actions, chips, eyebrow, field, fieldLabel, hint, panel } from "../styles";
import { PromptBox } from "./PromptBox";
import { type Draft, blankDraft, fromDraft, lengths, missing, startFrom, toDraft } from "./slots";
import { NEW, templateOf, useVideoBuilder } from "./use-video-builder";

const INPUT =
  "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30";

const SHAPE_HINTS: Record<string, string> = { landscape: "16:9", portrait: "9:16", square: "1:1" };
const FORMAT_LABELS: Record<BuilderFormat, string> = {
  mp4: "MP4",
  webm: "WebM, transparent",
  mov: "MOV, transparent",
};
// a grey chequerboard, so a see-through video can be seen to be see-through
const CHEQUER =
  "repeating-conic-gradient(color-mix(in srgb, currentColor 25%, transparent) 0% 25%, transparent 0% 50%) 50% / 24px 24px";

export type VideoBuilderProps = {
  api: VideoBuilderApi;
  /** For "Save a copy" of a finished video. */
  videos?: Pick<VideosApi, "exportCopy">;
  canSave?: boolean;
  /** Where a finished video can be downloaded from (the web app): "Download" is offered when given. */
  downloadHref?: (videoId: string) => string;
  /** Where the work is done: on this computer (the desktop) or on a service's worker (the web). */
  place?: "device" | "service";
  onOpenLibrary?: () => void;
};

/** Experimental: write a video from a template (title, quote, chart, name strap, captions),
 * have the words checked, watch it being drawn in a locked box, and keep it. */
export function VideoBuilder({
  api,
  videos,
  canSave = false,
  downloadHref,
  place = "device",
  onOpenLibrary,
}: VideoBuilderProps) {
  const b = useVideoBuilder(api);
  const { state } = b;
  const about = (
    <>
      Experimental.{" "}
      {place === "device"
        ? "Write a title, a quote, a chart, a name strap or captions and have it drawn on your computer."
        : "Write a title, a quote, a chart, a name strap or captions and have it drawn on the service's computer."}{" "}
      <details className="mt-1 text-sm">
        <summary className="w-fit cursor-pointer underline underline-offset-4">
          How is it made, and is it safe?
        </summary>
        <p className="mt-1.5">
          {place === "device"
            ? "Every word is checked against what you typed before anything is drawn. Each video is drawn in a locked box: it can reach nothing outside its own folder, and nothing is sent anywhere."
            : "Every word is checked against what you typed before anything is drawn. Each video is drawn in a locked box: it can reach nothing outside its own folder. The words you type are sent to the service and deleted when the video is made."}
        </p>
      </details>
    </>
  );
  if (state.loading || !state.component?.installed) {
    return (
      <div className="mx-auto grid w-full max-w-5xl gap-5 p-[clamp(1rem,3vw,2rem)]">
        <header className="grid gap-1.5">
          <h1 className="font-semibold text-step-2">Motion graphics</h1>
          <div className="max-w-3xl text-muted-foreground">{about}</div>
        </header>
        {state.error ? (
          <Notice tone="error" title="That did not work">
            {state.error}
          </Notice>
        ) : null}
        {state.loading ? (
          <output className="text-muted-foreground">Looking at Motion graphics…</output>
        ) : (
          <SetupCard
            component={state.component}
            onInstall={(bytes) => void b.install(bytes)}
            onRetry={() => void b.refresh()}
          />
        )}
      </div>
    );
  }
  // what goes above the form on every screen of the frame: what failed, and a missing tool
  const notices = (
    <>
      {state.error ? (
        <Notice tone="error" title="That did not work">
          {state.error}
        </Notice>
      ) : null}
      {state.component.tools && !state.component.tools.ready ? (
        <Notice
          tone="warn"
          title="One more thing is needed to make videos"
          actions={<Button onClick={() => void b.refresh()}>Check again</Button>}
        >
          {state.component.tools.message}
        </Notice>
      ) : null}
    </>
  );
  const recent = (
    <ProjectList
      projects={state.projects}
      catalogue={state.catalogue}
      selected={state.selected}
      onOpen={(id) => void b.open(id)}
      onNew={() => void b.open(NEW)}
    />
  );
  // the make frame (ADR-0093 U10): say it or fill in the form on the left, the video on the stage, the
  // projects under it; the say-it-then-check flow is unchanged
  return (
    <div data-workspace className={FRAME}>
      {state.selected ? (
        <Editor
          key={`${state.selected}:${state.project?.template ?? state.draft}`}
          api={b}
          videos={videos}
          canSave={canSave}
          downloadHref={downloadHref}
          onOpenLibrary={onOpenLibrary}
          lead={about}
          notices={notices}
          recent={recent}
        />
      ) : (
        <MakeScreen
          title="Motion graphics"
          lead={about}
          ask={
            <>
              {notices}
              <PromptBox
                busy={state.drafting}
                onSend={(request) => void b.draftFrom(request)}
                onForm={() => void b.open(NEW)}
              />
            </>
          }
          action={<p className={hint}>You check the form before anything is made.</p>}
          stage={
            <Stage
              state={{
                kind: "empty",
                icon: Clapperboard,
                title: "Your video appears here",
                text: "Say what to make, or start from an example. You check the form, preview it, then make it.",
              }}
            />
          }
          recent={recent}
        />
      )}
    </div>
  );
}

// ---- setting it up ---------------------------------------------------------------------------

function SetupCard({
  component,
  onInstall,
  onRetry,
}: {
  component: ReturnType<typeof useVideoBuilder>["state"]["component"];
  onInstall: (bytes: number) => void;
  onRetry: () => void;
}) {
  if (!component) {
    return (
      <Notice
        tone="error"
        title="Motion graphics could not be reached"
        actions={<Button onClick={onRetry}>Try again</Button>}
      >
        The engine did not answer. Try again in a moment.
      </Notice>
    );
  }
  const { plan, progress, sandbox } = component;
  if (!plan.supported) {
    return (
      <Notice tone="info" title="Not on this computer yet">
        Motion graphics was measured on Apple-silicon Macs and is not offered on other computers
        yet.
      </Notice>
    );
  }
  const installing = progress.state === "installing";
  const value = progress.total_bytes > 0 ? progress.done_bytes / progress.total_bytes : undefined;
  return (
    <section className={panel} aria-label="Set up Motion graphics">
      <h2 className="font-semibold text-lg">Set up Motion graphics</h2>
      <p className="text-muted-foreground">
        It needs a few parts that are not in the app. They are downloaded once, checked, and kept in
        the app's own folder; nothing else on your computer is changed.
      </p>
      <ul className="grid gap-1.5">
        {plan.parts.map((p) => (
          <li key={p.name} className="flex flex-wrap justify-between gap-x-4">
            <span>
              <strong>{p.name}</strong> <span className="text-muted-foreground">{p.version}</span>
            </span>
            <span className="text-muted-foreground tabular-nums">
              {megabytes(p.bytes)} · from {p.source}
            </span>
          </li>
        ))}
      </ul>
      <p className={hint}>
        {sandbox.network} {sandbox.telemetry}
      </p>
      {installing ? (
        <WorkingCard label={progress.message || "Setting up"}>
          <JobMeter
            title="Setting up Motion graphics"
            text={value === undefined ? "Starting" : `${Math.round(value * 100)}%`}
            value={value}
            label="Setup progress"
          />
        </WorkingCard>
      ) : (
        <div className={actions}>
          <Button type="button" size="lg" onClick={() => onInstall(plan.bytes)}>
            Download and set up ({megabytes(plan.bytes)})
          </Button>
          <span className="text-muted-foreground">Takes about a minute on a fast connection.</span>
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

// ---- the projects ----------------------------------------------------------------------------

function ProjectList({
  projects,
  catalogue,
  selected,
  onOpen,
  onNew,
}: {
  projects: BuilderProject[];
  catalogue: TemplateCatalogue | null;
  selected: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
}) {
  const kind = (id: string) =>
    id === "scenes" ? "Scenes" : (catalogue?.templates.find((t) => t.id === id)?.title ?? id);
  return (
    <nav aria-label="Your video projects" className="grid min-w-0 gap-2">
      <div className="flex items-center justify-between gap-3">
        <h2 className="m-0 font-semibold text-sm">Your videos</h2>
        <Button type="button" variant="outline" size="sm" onClick={onNew}>
          <Plus className="size-4" /> New video
        </Button>
      </div>
      {projects.length === 0 ? (
        <p className="m-0 text-muted-foreground text-sm">Nothing made here yet.</p>
      ) : (
        <ul className="m-0 flex list-none gap-2 overflow-x-auto p-0 pb-1">
          {projects.map((p) => (
            <li key={p.id} className="shrink-0">
              <button
                type="button"
                aria-current={selected === p.id ? "true" : undefined}
                onClick={() => onOpen(p.id)}
                className="grid w-48 min-w-0 gap-0.5 rounded-lg border p-2.5 text-start hover:border-primary/50 aria-[current=true]:border-primary aria-[current=true]:ring-2 aria-[current=true]:ring-primary/40"
              >
                <span className="block truncate font-medium text-sm">{p.title}</span>
                <span className="block truncate text-muted-foreground text-xs">
                  {kind(p.template)} · {String(p.slots.seconds)} seconds
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}

// ---- one project -----------------------------------------------------------------------------

type FieldProps = {
  info: FieldInfo;
  value: string;
  catalogue: TemplateCatalogue | null;
  onChange: (value: string) => void;
};

/** One field of the form, built from what the engine said about it. */
function FormField({ info, value, catalogue, onChange }: FieldProps) {
  const id = useId();
  const optional = info.required ? null : (
    <span className="font-normal text-muted-foreground"> (optional)</span>
  );
  if (info.kind === "text") {
    return (
      <div className={field}>
        <label className={fieldLabel} htmlFor={id}>
          {info.label}
          {optional}
        </label>
        <input
          id={id}
          className={INPUT}
          value={value}
          maxLength={info.max_chars}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    );
  }
  if (info.kind === "longtext" || info.kind === "lines" || info.kind === "rows") {
    return (
      <div className={field}>
        <label className={fieldLabel} htmlFor={id}>
          {info.label}
          {optional}
        </label>
        <textarea
          id={id}
          className={cn(INPUT, "min-h-24 font-[inherit]")}
          rows={info.kind === "longtext" ? 3 : 6}
          value={value}
          maxLength={info.kind === "longtext" ? info.max_chars : undefined}
          spellCheck={info.kind !== "rows"}
          onChange={(e) => onChange(e.target.value)}
        />
        {info.hint ? <p className={hint}>{info.hint}</p> : null}
      </div>
    );
  }
  if (info.kind === "seconds") {
    return (
      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>{info.label}</legend>
        <div className={cn(chips, "items-center")}>
          {lengths(info.min, info.max).map((n) => (
            <Chip key={n} aria-pressed={Number(value) === n} onClick={() => onChange(String(n))}>
              {n} seconds
            </Chip>
          ))}
          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
            or
            <input
              id={id}
              type="number"
              inputMode="numeric"
              min={info.min}
              max={info.max}
              aria-label={`${info.label} in seconds`}
              className={cn(INPUT, "w-20 py-1")}
              value={value}
              onChange={(e) => onChange(e.target.value)}
            />
            seconds
          </label>
        </div>
        <p className={hint}>
          From {info.min} to {info.max} seconds.
        </p>
      </fieldset>
    );
  }
  return (
    <fieldset className={cn(field, "m-0 border-0 p-0")}>
      <legend className={cn(fieldLabel, "mb-1.5")}>{info.label}</legend>
      <div className={chips}>
        {info.choices.map((c) => {
          const colours = info.id === "theme" ? catalogue?.themes[c.id as "midnight"] : undefined;
          return (
            <Chip key={c.id} aria-pressed={value === c.id} onClick={() => onChange(c.id)}>
              {colours ? (
                <span
                  aria-hidden="true"
                  className="me-1.5 inline-block size-3 rounded-full border align-middle"
                  style={{
                    background: `linear-gradient(135deg, ${colours.from}, ${colours.accent})`,
                  }}
                />
              ) : null}
              {c.label}
              {info.id === "shape" && SHAPE_HINTS[c.id] ? (
                <span className="opacity-85"> {SHAPE_HINTS[c.id]}</span>
              ) : null}
            </Chip>
          );
        })}
      </div>
    </fieldset>
  );
}

function CheckNotice({ check }: { check: BuilderCheck }) {
  if (check.ok) {
    return (
      <Notice tone="ok" title="The words are right">
        {check.message} ({check.checked} {check.checked === 1 ? "place" : "places"} looked at.)
      </Notice>
    );
  }
  return (
    <Notice tone="warn" title="The words on the screen are not right">
      {check.problems.length > 0
        ? check.problems.map((p) => (
            <span key={`${p.slot}:${p.code}`} className="block">
              {p.message}
            </span>
          ))
        : check.message}
    </Notice>
  );
}

/** A project of scenes (ADR-0096), written by the assistant or another app. The editor is the next stage (MX2). */
function ScenesSummary({ project }: { project: BuilderProject }) {
  const scenes = (project.slots.scenes ?? []) as unknown as {
    id: string;
    name: string;
    fields: { seconds: number };
  }[];
  return (
    <section aria-label="Scenes" className="grid max-w-xl gap-3 p-6">
      <h1 className="m-0 font-semibold text-lg tracking-tight">{project.title}</h1>
      <ol className="m-0 grid list-decimal gap-1 ps-5 text-sm">
        {scenes.map((scene) => (
          <li key={scene.id}>
            {scene.name}, {scene.fields.seconds} seconds
          </li>
        ))}
      </ol>
      <p className="m-0 text-muted-foreground text-sm">
        Ask the assistant to change these scenes or to make the video.
      </p>
    </section>
  );
}

function Editor({
  api,
  videos,
  canSave,
  downloadHref,
  onOpenLibrary,
  lead,
  notices,
  recent,
}: {
  api: ReturnType<typeof useVideoBuilder>;
  videos?: Pick<VideosApi, "exportCopy">;
  canSave: boolean;
  downloadHref?: (videoId: string) => string;
  onOpenLibrary?: () => void;
  lead: ReactNode;
  notices: ReactNode;
  recent: ReactNode;
}) {
  const formId = useId();
  const { state } = api;
  const { project, render, status, catalogue, stills, check, drafted } = state;
  const template = templateOf(state);
  const [draft, setDraft] = useState<Draft>({});
  const [format, setFormat] = useState<BuilderFormat | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const save = useSaveCopy();
  useEffect(() => {
    if (!template) return;
    if (project) setDraft(toDraft(template, project.slots));
    else if (drafted && drafted.template === template.id) {
      setDraft(startFrom(template, drafted.fields));
    } else setDraft(blankDraft(template));
  }, [project, template, drafted]);

  if (project?.template === "scenes") return <ScenesSummary project={project} />;
  if (!template) return null;
  const slots = fromDraft(template, draft);
  const dirty =
    !project ||
    JSON.stringify(slots) !== JSON.stringify(fromDraft(template, toDraft(template, project.slots)));
  const unfilled = missing(template, draft);
  const valid = unfilled === null;
  const working = render?.status === "working";
  const tooBig = status?.fit.verdict === "too_big";
  const busy = Boolean(status?.busy) && !working;
  const formats = project?.formats ?? template.formats;
  const chosen = format && formats.includes(format) ? format : (formats[0] ?? "mp4");

  async function keep(): Promise<BuilderProject | null> {
    if (!valid) return null;
    if (!dirty && project) return project;
    return api.save(slots);
  }

  async function previewIt() {
    const kept = await keep();
    if (kept) await api.showStills(kept);
  }

  async function checkIt() {
    const kept = await keep();
    if (kept) await api.checkWords(kept.id);
  }

  async function makeIt() {
    const kept = await keep();
    if (kept) await api.make(kept.id, chosen);
  }

  async function saveCopy(videoId: string) {
    if (!videos) return;
    setProblem(null);
    try {
      const done = await save({
        name: fileNameFor(
          project?.title || template?.title || "video",
          extensionOf(render?.video_url ?? "", "mp4"),
          "video",
        ),
        copy: (path) => videos.exportCopy(videoId, path),
      });
      if (done) setSaved(savedText(done));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The video could not be saved.");
    }
  }

  const renderCheck = render?.check ?? null;
  const ask = (
    <>
      {notices}
      <form
        id={formId}
        className="grid gap-5"
        aria-label="Your video"
        onSubmit={(e) => {
          e.preventDefault();
          void keep();
        }}
      >
        {!project && drafted && drafted.template === template.id ? (
          <Notice
            tone={drafted.warnings.length > 0 ? "warn" : "info"}
            title={
              drafted.warnings.length > 0
                ? "Check these before you go on"
                : "Here is what was understood"
            }
          >
            <span className="block">{drafted.summary}</span>
            {drafted.warnings.map((w) => (
              <span key={w} className="block">
                {w}
              </span>
            ))}
          </Notice>
        ) : null}
        {project ? (
          <p className={hint}>{template.title}</p>
        ) : (
          <fieldset className={cn(field, "m-0 border-0 p-0")}>
            <legend className={cn(fieldLabel, "mb-1.5")}>What to make</legend>
            <div className={chips}>
              {catalogue?.templates.map((t: TemplateInfo) => (
                <Chip
                  key={t.id}
                  aria-pressed={template.id === t.id}
                  onClick={() => api.chooseTemplate(t.id)}
                >
                  {t.title}
                </Chip>
              ))}
            </div>
            <p className={hint}>{template.description}</p>
          </fieldset>
        )}
        {template.fields.map((f) => (
          <FormField
            key={f.id}
            info={f}
            value={draft[f.id] ?? ""}
            catalogue={catalogue}
            onChange={(v) => setDraft((d) => ({ ...d, [f.id]: v }))}
          />
        ))}
        {formats.length > 1 ? (
          <fieldset className={cn(field, "m-0 border-0 p-0")}>
            <legend className={cn(fieldLabel, "mb-1.5")}>File</legend>
            <div className={chips}>
              {formats.map((f) => (
                <Chip key={f} aria-pressed={chosen === f} onClick={() => setFormat(f)}>
                  {FORMAT_LABELS[f]}
                </Chip>
              ))}
            </div>
            <p className={hint}>
              WebM and MOV keep the background clear, to lay over other video. MP4 is the most
              widely played.
            </p>
          </fieldset>
        ) : null}
        {status?.fit.verdict === "tight" ? (
          <Notice tone="warn" title="Memory is tight">
            {status.fit.reason}
          </Notice>
        ) : null}
        {tooBig ? (
          <Notice tone="warn" title="Not enough memory for a video">
            {status?.fit.reason}
          </Notice>
        ) : null}
      </form>
      {project?.code ? (
        <details className="grid gap-2 text-sm">
          <summary className="cursor-pointer font-medium">
            The page behind this video (read only)
          </summary>
          <pre className="mt-2 max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">
            {project.code}
          </pre>
        </details>
      ) : null}
    </>
  );

  const action = (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="lg"
          disabled={!valid || working || tooBig || busy}
          onClick={() => void makeIt()}
        >
          Make the video
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={!valid || working}
          onClick={() => void previewIt()}
        >
          Preview
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={!valid || working}
          onClick={() => void checkIt()}
        >
          Check the words
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <Button type="submit" form={formId} variant="ghost" size="sm" disabled={!valid || !dirty}>
          <Save className="size-4" /> Save
        </Button>
        {project?.can_undo ? (
          <Button type="button" variant="ghost" size="sm" onClick={() => void api.undo()}>
            <Undo2 className="size-4" /> Undo the last change
          </Button>
        ) : null}
        {project ? (
          confirmDelete ? (
            <>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={() => void api.remove(project.id)}
              >
                Delete it and its videos
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setConfirmDelete(false)}
              >
                Keep it
              </Button>
            </>
          ) : (
            <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="size-4" /> Delete
            </Button>
          )
        ) : null}
        {/* a way out: back to the first screen; what is saved stays in "Your videos" */}
        <Button type="button" variant="ghost" size="sm" onClick={() => void api.open(null)}>
          <X className="size-4" aria-hidden="true" /> {project ? "Close" : "Cancel"}
        </Button>
      </div>
      {unfilled ? <p className={hint}>Fill in the {unfilled.toLowerCase()} to go on.</p> : null}
      {busy ? <p className={hint}>A video is being made. Wait for it to finish.</p> : null}
    </div>
  );

  const videoActions: Action[] = [
    ...(canSave && videos && render?.video_id
      ? [
          {
            label: "Save a copy",
            onSelect: () => void saveCopy(render.video_id as string),
            icon: <Save aria-hidden="true" />,
          },
        ]
      : downloadHref && render?.video_id
        ? [
            {
              label: "Download",
              href: downloadHref(render.video_id),
              download: true,
              icon: <Save aria-hidden="true" />,
            },
          ]
        : []),
    ...(onOpenLibrary
      ? [{ label: "Your videos", onSelect: onOpenLibrary, icon: <Library aria-hidden="true" /> }]
      : []),
  ];

  const stills_ =
    stills.length > 0 ? (
      <section className="grid w-full justify-items-center gap-3" aria-label="Stills of your video">
        <div className="flex flex-wrap justify-center gap-3">
          {stills.map((s) => (
            <figure key={s.at} className="m-0 grid justify-items-center gap-1">
              <img
                src={s.url}
                alt={`A still of your video at ${s.at} seconds`}
                className="h-auto max-h-[30vh] max-w-full rounded-xl bg-black shadow-card"
                style={template.transparent ? { background: CHEQUER } : undefined}
              />
              <figcaption className={hint}>{s.at} seconds in</figcaption>
            </figure>
          ))}
        </div>
      </section>
    ) : null;

  const stage =
    working && render ? (
      <Stage
        state={{
          kind: "working",
          label: "Making your video",
          text: `${render.stage === "checking" ? "Checking the words" : "Drawing the video"}${render.progress > 0 ? ` · ${Math.round(render.progress * 100)}%` : ""}`,
          value: render.progress > 0 ? render.progress : undefined,
          onStop: () => void api.cancel(),
        }}
      />
    ) : render?.status === "done" && render.video_url ? (
      <Stage
        state={{
          kind: "result",
          children: (
            // biome-ignore lint/a11y/useMediaCaption: these videos are written words, with no speech to caption
            <video
              className="h-auto max-h-[60vh] max-w-full rounded-xl bg-black shadow-card"
              style={template.transparent ? { background: CHEQUER } : undefined}
              controls
              playsInline
              preload="metadata"
              poster={render.poster_url || undefined}
              src={render.video_url}
            />
          ),
          caption: (
            <span className="grid gap-1">
              <span>
                <strong className="font-medium text-foreground">Your video is ready</strong>
                {" · "}
                It took {Math.max(1, Math.round(render.elapsed_s ?? 0))} seconds and is saved in
                Your videos.
                {renderCheck?.ok
                  ? ` Every word on the screen was checked against what you typed (${renderCheck.checked} places).`
                  : ""}
                {render.blocked > 0
                  ? ` It tried to reach outside its folder ${render.blocked} time${render.blocked === 1 ? "" : "s"}; every try was refused.`
                  : ""}
              </span>
              {saved ? <output>{saved}</output> : null}
              {problem ? <output className="text-destructive">{problem}</output> : null}
            </span>
          ),
          actions: videoActions,
        }}
      />
    ) : render?.status === "failed" || render?.status === "cancelled" ? (
      <div className="grid w-full justify-items-center gap-3">
        <Stage
          state={{
            kind: "error",
            title: render.status === "cancelled" ? "Stopped" : "The video could not be made",
            message: render.error ?? "It did not finish.",
          }}
        />
        {renderCheck && !renderCheck.ok && renderCheck.problems.length > 0 ? (
          <div className="w-full max-w-xl">
            <CheckNotice check={renderCheck} />
          </div>
        ) : null}
      </div>
    ) : stills_ || check ? (
      <div className="grid w-full justify-items-center gap-4">
        {check ? (
          <div className="w-full max-w-xl">
            <CheckNotice check={check} />
          </div>
        ) : null}
        {stills_}
      </div>
    ) : (
      <Stage
        state={{
          kind: "empty",
          icon: Clapperboard,
          title: "Your video appears here",
          text: "Preview it to see a few stills, check the words, then make it.",
        }}
      />
    );

  return (
    <MakeScreen
      title="Motion graphics"
      lead={lead}
      ask={ask}
      action={action}
      stage={stage}
      recent={recent}
    />
  );
}
