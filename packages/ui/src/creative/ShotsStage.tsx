"use client";
// The Shots step (ADR-0090 decisions 6 and 8): the honest panel before anything starts, the run with its Stop,
// the preview over the song, and each shot's still with its takes. Nothing replaces a chosen take without a click.
import {
  type CreativeApi,
  type CreativeProject,
  type Shot,
  type StillMode,
  type StillsEstimate,
  type Take,
  gigabytes,
} from "@wasifyai/client";
import { useEffect, useState } from "react";
import { Badge } from "../components/badge";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { JobMeter, WorkingCard } from "../components/create";
import { Notice } from "../components/notice";
import { Segmented } from "../components/segmented";
import { Spinner } from "../components/spinner";
import { actions, hint, panel } from "../styles";

const MODES = [
  { value: "reference", label: "From reference pictures" },
  { value: "plain", label: "Plain, about twice as fast" },
];

function minutes(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} seconds`;
  return `${Math.round(seconds / 60)} minutes`;
}

function chosenOf(takes: Take[] | undefined): Take | undefined {
  return takes?.find((t) => t.chosen);
}

/** Before anything starts: how many, how long, how much disk, and whether it fits. */
function HonestPanel({
  api,
  project,
  mode,
  onMode,
  act,
}: {
  api: CreativeApi;
  project: CreativeProject;
  mode: StillMode;
  onMode: (mode: StillMode) => void;
  act: (work: () => Promise<CreativeProject>) => Promise<void>;
}) {
  const [redo, setRedo] = useState(false);
  const [ask, setAsk] = useState<StillsEstimate | null>(null);
  const { missing, out_of_date: stale, run } = project.shots;
  const id = project.id;
  const left = missing.length;
  const old = stale.length;
  // biome-ignore lint/correctness/useExhaustiveDependencies: left and old say when the numbers changed
  useEffect(() => {
    let current = true;
    api
      .estimateStills(id, mode, redo)
      .then((found) => current && setAsk(found))
      .catch(() => current && setAsk(null));
    return () => {
      current = false;
    };
  }, [api, id, mode, redo, left, old]);

  if (!ask) return <Spinner />;
  const none = ask.count === 0;
  const blocked = none || !ask.ready || ask.fit === "too_big";
  const stopped = run?.kind === "stills" && run.status !== "done" && run.status !== "running";
  return (
    <section aria-label="Before you start" className={`${panel} grid gap-3`}>
      <h2 className="m-0 font-semibold text-base">
        {none ? "Every shot has its still" : `${ask.count} stills to make`}
      </h2>
      {none ? null : (
        <>
          <Segmented
            label="How the stills are made"
            size="sm"
            value={mode}
            onValueChange={(v) => onMode(v as StillMode)}
            options={MODES}
          />
          <p className="m-0 text-sm">
            About {minutes(ask.seconds_low)} to {minutes(ask.seconds_high)}
            {ask.measured ? ", going by the stills made so far" : ""}, about {gigabytes(ask.bytes)}{" "}
            on the disk, with {gigabytes(ask.free_bytes)} free.
          </p>
          <p className={`${hint} m-0`}>
            {ask.portraits
              ? `${ask.portraits === 1 ? "1 person gets" : `${ask.portraits} people get`} two pictures first, so that every shot starts from the same face. `
              : ""}
            Each still is saved as it is made and goes into your Library. Stop keeps them. Of the
            whole plan, {ask.motions.Hold} shots hold, {ask.motions.Animate} animate and{" "}
            {ask.motions.Sing} sing. The preview shows all of them as stills.
          </p>
        </>
      )}
      {ask.out_of_date ? (
        <Checkbox
          label={`Also make again the ${ask.out_of_date === 1 ? "still" : `${ask.out_of_date} stills`} that the plan has moved on from`}
          checked={redo}
          onCheckedChange={setRedo}
        />
      ) : null}
      {ask.fit === "tight" ? (
        <Notice tone="warn" title="The disk is nearly full">
          It should fit, with little room left over.
        </Notice>
      ) : null}
      {ask.fit === "too_big" ? (
        <Notice tone="error" title="There is not enough room on the disk">
          Make room, or choose fewer shots in the plan.
        </Notice>
      ) : null}
      {ask.ready ? null : (
        <Notice tone="warn" title="The picture model is not ready">
          {ask.step ?? "Choose a picture model with the model button at the top."}
        </Notice>
      )}
      {none ? null : (
        <div className={actions}>
          <Button
            type="button"
            disabled={blocked}
            onClick={() => void act(() => api.makeStills(id, mode, redo))}
          >
            {stopped ? "Go on" : "Start"}
          </Button>
        </div>
      )}
    </section>
  );
}

function RunNotice({ project }: { project: CreativeProject }) {
  const run = project.shots.run;
  if (!run || project.shots_live) return null;
  const done = `${run.finished} of ${run.total} done.`;
  if (run.status === "stopped") {
    return (
      <Notice tone="info" title="Stopped">
        {done} What was made is kept, so going on makes only what is missing.
      </Notice>
    );
  }
  if (run.status === "interrupted") {
    return (
      <Notice tone="warn" title="It stopped when the app closed">
        What was made is kept, so going on makes only what is missing.
      </Notice>
    );
  }
  if (run.status === "failed") {
    return (
      <Notice tone="error" title="It did not finish">
        {run.error}
      </Notice>
    );
  }
  return null;
}

function Preview({ project }: { project: CreativeProject }) {
  const preview = project.shots.preview;
  if (!preview?.url) return null;
  return (
    <figure className="m-0 grid gap-1.5">
      {/* biome-ignore lint/a11y/useMediaCaption: the song has no timed words yet; captions come with the Cut step */}
      <video
        key={preview.url}
        src={preview.url}
        controls
        aria-label="The preview over the song"
        className="max-h-[50dvh] w-full rounded-md bg-black"
      />
      <figcaption className={hint}>
        A draft: stills with a camera move, cut on the plan's times. Joined in{" "}
        {minutes(preview.took_s)}.
        {preview.empty_shots
          ? ` ${preview.empty_shots === 1 ? "1 shot is" : `${preview.empty_shots} shots are`} black, having no still.`
          : ""}
        {preview.current ? "" : " The shots have changed since: make it again to see them."}
      </figcaption>
    </figure>
  );
}

function Still({ cover, alt }: { cover: string | undefined; alt: string }) {
  return cover ? (
    <img src={cover} alt={alt} className="aspect-video w-full rounded-md object-cover" />
  ) : (
    <div className="grid aspect-video w-full place-items-center rounded-md bg-muted text-muted-foreground text-xs">
      No still yet
    </div>
  );
}

/** The selected shot, large, with its takes and Redo. */
function Selected({
  api,
  project,
  shot,
  number,
  mode,
  coverOf,
  act,
}: {
  api: CreativeApi;
  project: CreativeProject;
  shot: Shot;
  number: number;
  mode: StillMode;
  coverOf: (kind: string, id: string) => string | undefined;
  act: (work: () => Promise<CreativeProject>) => Promise<void>;
}) {
  const takes = project.shots.takes[shot.id] ?? [];
  const chosen = chosenOf(takes);
  const busy = project.shots_live || project.live;
  return (
    <section aria-label={`Shot ${number}`} className={`${panel} grid gap-2`}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="m-0 font-semibold text-base">Shot {number}</h2>
        {chosen?.out_of_date ? <Badge variant="destructive">Out of date</Badge> : null}
        <span className="grow" />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => void act(() => api.redoShot(project.id, shot.id, mode))}
        >
          {takes.length ? "Make it again" : "Make this still"}
        </Button>
      </div>
      <Still
        cover={chosen ? coverOf(chosen.kind, chosen.item_id) : undefined}
        alt={`Shot ${number}: ${shot.shows}`}
      />
      <p className="m-0 text-sm">{shot.shows}</p>
      {takes.length > 1 ? (
        <fieldset className="m-0 grid gap-1 border-0 p-0">
          <legend className={`${hint} p-0`}>Versions: the one you choose is used</legend>
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
            {takes.map((take, i) => (
              <li key={take.id}>
                <button
                  type="button"
                  aria-pressed={take.chosen}
                  aria-label={`Version ${i + 1} of shot ${number}${take.out_of_date ? ", out of date" : ""}`}
                  disabled={busy}
                  onClick={() => void act(() => api.chooseTake(project.id, shot.id, take.id))}
                  className={`w-20 cursor-pointer rounded-md border-2 p-0.5 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 ${take.chosen ? "border-primary" : "border-transparent"}`}
                >
                  <Still cover={coverOf(take.kind, take.item_id)} alt="" />
                </button>
              </li>
            ))}
          </ul>
        </fieldset>
      ) : null}
    </section>
  );
}

export function ShotsStage({
  api,
  project,
  selected,
  onSelect,
  mode,
  onMode,
  coverOf,
  act,
}: {
  api: CreativeApi;
  project: CreativeProject;
  selected: string | null;
  onSelect: (id: string) => void;
  mode: StillMode;
  onMode: (mode: StillMode) => void;
  coverOf: (kind: string, id: string) => string | undefined;
  act: (work: () => Promise<CreativeProject>) => Promise<void>;
}) {
  const shots = project.plan?.shots ?? [];
  const run = project.shots.run;
  const at = shots.findIndex((s) => s.id === selected);
  const current = at < 0 ? undefined : shots[at];
  return (
    <>
      <RunNotice project={project} />
      <Preview project={project} />
      {project.shots_live && run ? (
        <WorkingCard
          label={run.stage || "Making the stills"}
          onCancel={() => void act(() => api.stopStills(project.id))}
        >
          {run.kind === "stills" ? (
            <JobMeter
              title="The stills"
              text={`${run.finished} of ${run.total}`}
              value={run.total ? run.finished / run.total : 0}
              label="Stills made"
            />
          ) : null}
        </WorkingCard>
      ) : (
        <HonestPanel api={api} project={project} mode={mode} onMode={onMode} act={act} />
      )}
      {current ? (
        <Selected
          api={api}
          project={project}
          shot={current}
          number={at + 1}
          mode={mode}
          coverOf={coverOf}
          act={act}
        />
      ) : null}
      <ol className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2 p-0">
        {shots.map((shot, i) => {
          const takes = project.shots.takes[shot.id] ?? [];
          const chosen = chosenOf(takes);
          const on = shot.id === selected;
          return (
            <li key={shot.id}>
              <button
                type="button"
                aria-pressed={on}
                aria-label={`Shot ${i + 1}${chosen?.out_of_date ? ", out of date" : ""}${takes.length ? "" : ", no still yet"}`}
                onClick={() => onSelect(shot.id)}
                className={`grid w-full cursor-pointer gap-1 rounded-md border p-1 text-start outline-none hover:border-primary/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 ${on ? "border-primary ring-1 ring-primary" : ""}`}
              >
                <Still cover={chosen ? coverOf(chosen.kind, chosen.item_id) : undefined} alt="" />
                <span className="flex items-center gap-1 text-xs">
                  <span className="font-semibold">Shot {i + 1}</span>
                  {takes.length > 1 ? (
                    <span className="text-muted-foreground">{takes.length} versions</span>
                  ) : null}
                  {chosen?.out_of_date ? <Badge variant="destructive">Out of date</Badge> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </>
  );
}
