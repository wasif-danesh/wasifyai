"use client";
// One project on one screen (the amendment to ADR-0090): the Make panel, the stage, the media rail, and the
// steps in the top bar. In the Plan step the stage is the plan, with its song strip, parts and shots, and
// planning with its progress and Stop, or going on after a stop or a crash.
import type {
  CreativeApi,
  CreativeProject,
  PlanEdit,
  PlanLogEntry,
  Shot,
  ShotMotion,
  SongFacts,
} from "@wasifyai/client";
import { ArrowLeft, ChevronLeft, ChevronRight, Plus, Trash2, Undo2 } from "lucide-react";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Badge } from "../components/badge";
import { Button } from "../components/button";
import { JobMeter, WorkingCard } from "../components/create";
import { ConfirmDialog, Modal } from "../components/dialog";
import { Notice } from "../components/notice";
import { Player } from "../components/player";
import { Segmented } from "../components/segmented";
import { Select } from "../components/select";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { actions, hint } from "../styles";
import { PageHeader } from "../window-bar";
import { AnalysisCard, BriefForm, useAnalysis } from "./BriefForm";
import type { CreativeSong } from "./Creative";
import { type CreativeAssistant, type CreativeScreen, MakePanel } from "./MakePanel";
import { MediaRail } from "./MediaRail";
import { type ProjectCreations, useProjectMedia } from "./use-project-media";

const POLL_MS = 1000;
const MOTIONS = [
  { value: "Hold", label: "Hold" },
  { value: "Animate", label: "Animate" },
  { value: "Sing", label: "Sing" },
];
const SOON = "Comes in a later stage of Creative Studio";
// the later steps of ADR-0090: shown so the shape of the work can be seen, off until they are built
const STEPS = [
  { value: "plan", label: "Plan" },
  { value: "shots", label: <span title={SOON}>Shots</span>, disabled: true },
  { value: "cut", label: <span title={SOON}>Cut</span>, disabled: true },
];

function clock(seconds: number): string {
  const whole = Math.floor(seconds);
  const tenth = Math.floor((seconds - whole) * 10);
  return `${Math.floor(whole / 60)}:${(whole % 60).toString().padStart(2, "0")}.${tenth}`;
}

const say = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

/** Above this width the steps sit in the window's top bar, as in the mockup; below it there is no room. */
const ROOMY = "(min-width: 85rem)";
const roomy = {
  subscribe: (changed: () => void) => {
    if (typeof window.matchMedia !== "function") return () => {};
    const media = window.matchMedia(ROOMY);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  },
  now: () => typeof window.matchMedia === "function" && window.matchMedia(ROOMY).matches,
};

export function ProjectView({
  api,
  songs,
  id,
  model,
  assistant,
  creations,
  onBack,
  onMakeSong,
  onOpenScreen,
}: {
  api: CreativeApi;
  songs: () => Promise<CreativeSong[]>;
  id: string;
  model?: ReactNode;
  assistant?: CreativeAssistant;
  creations?: ProjectCreations;
  onBack: () => void;
  onMakeSong?: () => void;
  onOpenScreen?: (screen: CreativeScreen) => void;
}) {
  const [project, setProject] = useState<CreativeProject | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);
  const [song, setSong] = useState<CreativeSong | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [chatWorking, setChatWorking] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const wide = useSyncExternalStore(roomy.subscribe, roomy.now);
  const analysis = useAnalysis(api);
  const live = project?.live ?? false;
  const trackId = project?.brief.track_id;
  const revision = project?.revision ?? 0;
  const media = useProjectMedia(api, creations, id, trackId);
  // the revision each of the assistant's changes made, so its card can take that change back
  const madeByTools = useRef(new Map<string, number>());

  const read = useCallback(async () => {
    try {
      setProject(await api.get(id));
    } catch (e) {
      setProblem(say(e, "The project could not be read."));
    }
  }, [api, id]);

  useEffect(() => {
    void read();
  }, [read]);
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => void read(), POLL_MS);
    return () => clearInterval(timer);
  }, [live, read]);
  useEffect(() => {
    if (!trackId) return;
    songs()
      .then((all) => setSong(all.find((s) => s.id === trackId) ?? null))
      .catch(() => setSong(null));
  }, [songs, trackId]);
  // a change taken back stays taken back, though a later change will reach the same number
  useEffect(() => {
    for (const [tool, at] of madeByTools.current) {
      if (at > revision) madeByTools.current.set(tool, Number.POSITIVE_INFINITY);
    }
  }, [revision]);

  // every change comes back as the whole project; a refusal says why and changes nothing
  const act = useCallback(async (work: () => Promise<CreativeProject>) => {
    setProblem(null);
    try {
      setProject(await work());
    } catch (e) {
      setProblem(say(e, "That did not work."));
    }
  }, []);

  const onChanged = useCallback(
    (toolId: string, action: string) => {
      void act(async () => {
        const fresh = await api.get(id);
        if (action === "creative.edit_plan") madeByTools.current.set(toolId, fresh.revision);
        return fresh;
      });
    },
    [act, api, id],
  );
  const undoOfTool = useCallback(
    (toolId: string) => {
      const at = madeByTools.current.get(toolId);
      if (at === undefined) return null; // from an earlier visit, or nothing changed
      return {
        undone: revision < at,
        undo: () => {
          void act(async () => {
            let fresh = await api.undo(id);
            while (fresh.revision >= at) fresh = await api.undo(id);
            return fresh;
          });
        },
      };
    },
    [act, api, id, revision],
  );

  if (!project) {
    return (
      <div className="p-6">
        {problem ? (
          <Notice tone="error" title="The project could not be opened">
            {problem}
          </Notice>
        ) : (
          <Spinner />
        )}
      </div>
    );
  }

  const ready = analysis.state?.state === "ready";
  const shots = project.plan?.shots ?? [];
  const at = shots.findIndex((s) => s.id === selected);
  const bar = <ProjectBar project={project} onBack={onBack} onLog={() => setShowLog(true)} />;
  return (
    <div className="@container flex h-full min-h-0 flex-1 flex-col" data-slot="creative-project">
      <PageHeader title={wide} className="flex h-14 shrink-0 items-center gap-4 border-b px-6 pt-1">
        <div className="flex min-w-0 flex-1 items-center gap-3 ps-2 text-sm">
          <div className="shrink-0">{model}</div>
          {wide ? bar : null}
        </div>
      </PageHeader>
      {wide ? null : (
        <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">{bar}</div>
      )}
      <div className="flex min-h-0 flex-1 flex-col overflow-auto @4xl:grid @4xl:grid-cols-[19rem_minmax(0,1fr)_8.5rem] @4xl:overflow-hidden">
        <aside
          aria-label="Make panel"
          className="order-3 border-t @4xl:order-none @4xl:min-h-0 @4xl:border-t-0 @4xl:border-e"
        >
          <MakePanel
            api={api}
            project={project}
            selected={selected}
            selectedName={at < 0 ? null : `shot ${at + 1}`}
            assistant={assistant}
            creations={creations}
            added={
              new Set([`track:${trackId}`, ...media.tags.map((m) => `${m.kind}:${m.item_id}`)])
            }
            problem={media.problem}
            onAdd={(kind, item) => void media.add(kind, item, selected ?? undefined)}
            onOpenScreen={onOpenScreen}
            onChanged={onChanged}
            onWorking={setChatWorking}
            undoOfTool={undoOfTool}
          />
        </aside>
        <section
          aria-label="The plan"
          inert={chatWorking}
          className="order-1 grid content-start gap-4 p-4 @4xl:order-none @4xl:min-h-0 @4xl:overflow-auto"
        >
          {changing ? (
            <BriefForm
              api={api}
              songs={songs}
              initial={project.brief}
              initialTitle={project.title}
              submitLabel="Save and plan again"
              onMakeSong={onMakeSong}
              onCancel={() => setChanging(false)}
              onSubmit={async (title, brief) => {
                await api.change(project.id, { title: title || undefined, brief });
                setProject(await api.plan(project.id, true));
                setChanging(false);
              }}
            />
          ) : (
            <>
              {problem ? (
                <Notice tone="error" title="That did not work">
                  {problem}
                </Notice>
              ) : null}
              <div className="grid gap-0.5">
                <p className="m-0 font-semibold text-lg">{project.brief.idea}</p>
                <p className={`${hint} m-0`}>{factsLine(project)}</p>
              </div>
              {song ? (
                <Player src={song.url} title={song.title} duration={song.seconds} waveform />
              ) : null}
              {live ? (
                <WorkingCard
                  label={project.stage || "Planning"}
                  onCancel={() => void act(() => api.stop(project.id))}
                >
                  <JobMeter
                    title="Planning"
                    text={`${Math.round(project.progress * 100)}%`}
                    value={project.progress}
                    label="Planning progress"
                  />
                </WorkingCard>
              ) : null}
              {!live && project.status !== "planned" ? (
                <>
                  <AnalysisCard analysis={analysis} />
                  <Stopped
                    project={project}
                    ready={ready}
                    onGo={(again) => void act(() => api.plan(project.id, again))}
                    onChange={() => setChanging(true)}
                  />
                </>
              ) : null}
              {project.plan && (project.status === "planned" || (live && project.revision > 0)) ? (
                <PlanBody
                  project={project}
                  api={api}
                  busy={live}
                  selected={selected}
                  onSelect={setSelected}
                  act={act}
                  onChangeBrief={() => setChanging(true)}
                />
              ) : null}
            </>
          )}
        </section>
        <aside
          aria-label="Media of this project"
          className="order-2 border-t @4xl:order-none @4xl:min-h-0 @4xl:overflow-auto @4xl:border-t-0 @4xl:border-s"
        >
          <MediaRail
            entries={media.entries}
            tags={media.tags}
            songId={trackId}
            shots={shots}
            onRemove={(kind, item) => void media.remove(kind, item)}
          />
        </aside>
      </div>
      {showLog ? <PlanLog api={api} id={project.id} onClose={() => setShowLog(false)} /> : null}
    </div>
  );
}

function factsLine(project: CreativeProject): string {
  const { facts, plan, brief } = project;
  const seconds = facts.seconds ?? 0;
  const parts = [
    brief.style,
    brief.shape,
    seconds
      ? `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`
      : "",
    plan ? `${plan.shots.length} shots` : "",
  ];
  return parts.filter(Boolean).join(" · ");
}

function ProjectBar({
  project,
  onBack,
  onLog,
}: {
  project: CreativeProject;
  onBack: () => void;
  onLog: () => void;
}) {
  return (
    <>
      <Button type="button" variant="ghost" size="icon" aria-label="Back" onClick={onBack}>
        <ArrowLeft aria-hidden />
      </Button>
      <h1 className="m-0 min-w-0 grow basis-48 truncate font-semibold text-sm">{project.title}</h1>
      <span className="shrink-0 text-muted-foreground text-xs">
        {project.revision ? `Plan ${project.revision} · saved` : "Not planned yet"}
      </span>
      <span className="grow" />
      <Segmented label="Step" value="plan" onValueChange={() => {}} options={STEPS} />
      <span className="grow" />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!project.revision}
        onClick={onLog}
      >
        Planning log
      </Button>
      <span title={SOON}>
        <Button type="button" size="sm" disabled>
          Make the stills
        </Button>
      </span>
    </>
  );
}

function PlanLog({ api, id, onClose }: { api: CreativeApi; id: string; onClose: () => void }) {
  const [log, setLog] = useState<PlanLogEntry[] | null>(null);
  useEffect(() => {
    api
      .log(id)
      .then(setLog)
      .catch(() => setLog([]));
  }, [api, id]);
  return (
    <Modal label="What the writer was asked" onClose={onClose} wide>
      <div className="grid max-h-[70dvh] gap-3 overflow-auto">
        {log === null ? <Spinner /> : null}
        {log?.length === 0 ? (
          <p className={`${hint} m-0`}>Nothing was kept for this plan.</p>
        ) : null}
        {(log ?? []).map((entry, i) => (
          <div key={`log-${i.toString()}`} className="grid gap-1">
            <h3 className="m-0 font-semibold text-sm">{entry.step}</h3>
            <pre className="m-0 max-h-48 overflow-auto whitespace-pre-wrap text-muted-foreground text-xs">
              {entry.asked}
            </pre>
            <pre className="m-0 max-h-48 overflow-auto whitespace-pre-wrap text-xs">
              {entry.said}
            </pre>
          </div>
        ))}
        <div className={actions}>
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function Stopped({
  project,
  ready,
  onGo,
  onChange,
}: {
  project: CreativeProject;
  ready: boolean;
  onGo: (again: boolean) => void;
  onChange: () => void;
}) {
  const said = {
    draft: { tone: "info", title: "Not planned yet", text: "The brief is saved." },
    planning: { tone: "info", title: "Planning", text: "" },
    planned: { tone: "info", title: "Planned", text: "" },
    stopped: {
      tone: "info",
      title: "The plan was stopped",
      text: "What it had written is kept, so going on does not start again.",
    },
    interrupted: {
      tone: "warn",
      title: "The plan stopped when the app closed",
      text: "What it had written is kept, so going on does not start again.",
    },
    failed: { tone: "error", title: "The plan did not finish", text: project.error ?? "" },
  }[project.status] as { tone: "info" | "warn" | "error"; title: string; text: string };
  return (
    <Notice
      tone={said.tone}
      title={said.title}
      actions={
        <div className={actions}>
          <Button type="button" disabled={!ready} onClick={() => onGo(false)}>
            {project.status === "draft" ? "Plan it" : "Go on"}
          </Button>
          {project.status === "draft" ? null : (
            <Button type="button" variant="outline" disabled={!ready} onClick={() => onGo(true)}>
              Start again
            </Button>
          )}
          <Button type="button" variant="ghost" onClick={onChange}>
            Change the brief
          </Button>
        </div>
      }
    >
      {said.text}
    </Notice>
  );
}

function SongStrip({ facts, shots }: { facts: SongFacts; shots: Shot[] }) {
  const seconds = facts.seconds ?? shots[shots.length - 1]?.end ?? 0;
  if (!seconds) return null;
  const at = (t: number) => `${(t / seconds) * 100}%`;
  const strength = { low: 0.25, mid: 0.5, high: 0.85 } as Record<string, number>;
  return (
    <figure className="m-0 grid gap-1.5">
      <div className="relative h-10 overflow-hidden rounded-md border bg-muted">
        {(facts.sections ?? []).map((s) => (
          <div
            key={s.start}
            className="absolute inset-y-0 bg-primary"
            style={{
              left: at(s.start),
              width: at(s.end - s.start),
              opacity: strength[s.label] ?? 0.5,
            }}
          />
        ))}
        {shots.slice(1).map((s) => (
          <div
            key={s.id}
            className="absolute inset-y-0 w-px bg-background"
            style={{ left: at(s.start) }}
          />
        ))}
      </div>
      <figcaption className={hint}>
        {Math.round(seconds)} s{facts.bpm ? `, about ${Math.round(facts.bpm)} beats a minute` : ""},{" "}
        {shots.length} shots. Darker is louder; the thin lines are the cuts.
        {facts.lines_timed === false ? " The song's lines could not be timed." : ""}
      </figcaption>
    </figure>
  );
}

function PlanBody({
  project,
  api,
  busy,
  selected,
  onSelect,
  act,
  onChangeBrief,
}: {
  project: CreativeProject;
  api: CreativeApi;
  busy: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
  act: (work: () => Promise<CreativeProject>) => Promise<void>;
  onChangeBrief: () => void;
}) {
  const plan = project.plan;
  const [again, setAgain] = useState(false);
  if (!plan) return null;
  const edit = (edits: PlanEdit[]) => act(() => api.edit(project.id, edits));
  const plain = plan.shots.filter((s) => s.fallback).length;
  const lastId = plan.shots[plan.shots.length - 1]?.id;
  return (
    <>
      <SongStrip facts={project.facts} shots={plan.shots} />
      <div className={actions}>
        <Button
          type="button"
          variant="outline"
          disabled={busy || project.revision < 2}
          onClick={() => void act(() => api.undo(project.id))}
        >
          <Undo2 aria-hidden /> Undo
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={onChangeBrief}>
          Change the brief
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={() => setAgain(true)}>
          Plan again
        </Button>
        {project.elapsed_s ? (
          <span className={hint}>Planned in {Math.round(project.elapsed_s)} s.</span>
        ) : null}
      </div>
      {plain ? (
        <Notice
          tone="warn"
          title={plain === 1 ? "1 shot is in plain words" : `${plain} shots are in plain words`}
        >
          The model's sentence for these did not pass the checks. Rewrite them, or try another idea
          for that part.
        </Notice>
      ) : null}
      {plan.beats.map((part, b) => {
        const shots = plan.shots.filter((s) => s.beat === b);
        if (shots.length === 0) return null;
        return (
          <section key={`part-${b.toString()}`} className="grid gap-2" aria-label={`Part ${b + 1}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="m-0 font-semibold text-base">
                Part {b + 1}: {part.what}
              </h2>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => void act(() => api.rewritePart(project.id, b))}
              >
                Try another idea for this part
              </Button>
            </div>
            <ol className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3 p-0">
              {shots.map((s) => (
                <ShotCard
                  key={`${s.id}-${project.revision}`}
                  shot={s}
                  number={plan.shots.indexOf(s) + 1}
                  last={s.id === lastId}
                  only={plan.shots.length === 1}
                  busy={busy}
                  selected={s.id === selected}
                  onSelect={() => onSelect(s.id)}
                  edit={edit}
                />
              ))}
            </ol>
          </section>
        );
      })}
      {again ? (
        <ConfirmDialog
          title="Plan this again from the start?"
          message="A new plan is written. You can get this one back with Undo."
          confirmLabel="Plan again"
          destructive={false}
          onCancel={() => setAgain(false)}
          onConfirm={() => {
            setAgain(false);
            void act(() => api.plan(project.id, true));
          }}
        />
      ) : null}
    </>
  );
}

function ShotCard({
  shot,
  number,
  last,
  only,
  busy,
  selected,
  onSelect,
  edit,
}: {
  shot: Shot;
  number: number;
  last: boolean;
  only: boolean;
  busy: boolean;
  selected: boolean;
  onSelect: () => void;
  edit: (edits: PlanEdit[]) => Promise<void>;
}) {
  const [words, setWords] = useState(shot.shows);
  const label = `shot ${number}`;
  return (
    <li
      className={`grid content-start gap-2 rounded-lg border bg-surface p-3 ${selected ? "border-primary ring-1 ring-primary" : ""}`}
      onFocusCapture={onSelect}
    >
      {/* where the shot's still goes in the Shots step */}
      <div aria-hidden className="aspect-[5/2] rounded-md bg-muted" />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <button
          type="button"
          aria-pressed={selected}
          className="cursor-pointer rounded-sm bg-transparent p-0 font-semibold outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          onClick={onSelect}
        >
          Shot {number}
        </button>
        <span className="text-muted-foreground tabular-nums">
          {clock(shot.start)} to {clock(shot.end)}
        </span>
        <Badge variant="outline">{shot.camera}</Badge>
        {shot.place ? <Badge variant="outline">{shot.place}</Badge> : null}
        {shot.who.map((w) => (
          <Badge key={w} variant="secondary">
            {w}
          </Badge>
        ))}
        {shot.fallback ? <Badge variant="destructive">Plain words</Badge> : null}
      </div>
      <Textarea
        aria-label={`What ${label} shows`}
        rows={2}
        disabled={busy}
        value={words}
        onChange={(e) => setWords(e.target.value)}
        onBlur={() => {
          const next = words.trim();
          if (next && next !== shot.shows) {
            void edit([{ op: "set_shot", shot_id: shot.id, shows: next }]);
          }
        }}
      />
      {shot.line ? <p className={`${hint} m-0 italic`}>Sung here: {shot.line}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label={`Motion of ${label}`}
          className="w-32"
          disabled={busy}
          value={shot.motion}
          options={MOTIONS}
          onValueChange={(v) =>
            void edit([{ op: "set_shot", shot_id: shot.id, motion: v as ShotMotion }])
          }
        />
        {last ? null : (
          <span className="flex items-center gap-1 text-sm">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={busy}
              aria-label={`End ${label} one beat earlier`}
              onClick={() => void edit([{ op: "move_cut", shot_id: shot.id, by_beats: -1 }])}
            >
              <ChevronLeft aria-hidden />
            </Button>
            Cut
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={busy}
              aria-label={`End ${label} one beat later`}
              onClick={() => void edit([{ op: "move_cut", shot_id: shot.id, by_beats: 1 }])}
            >
              <ChevronRight aria-hidden />
            </Button>
          </span>
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => void edit([{ op: "add_shot", after: shot.id }])}
        >
          <Plus aria-hidden /> Add a shot after
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy || only}
          onClick={() => void edit([{ op: "delete_shot", shot_id: shot.id }])}
        >
          <Trash2 aria-hidden /> Remove
        </Button>
      </div>
    </li>
  );
}
