"use client";
// Motion on the Shots step (ADR-0090 decision 6, stage CS4): Make it better, sharp clips for the shots the plan marks
// Animate, is the default (owner, 2026-11-05); a quick draft of about 30 seconds is a soft preview of the motion. The panel says before Start which shots, how long and how much disk, and the time
// is corrected by the clips made on this computer.
import {
  type CreativeApi,
  type CreativeProject,
  type MotionEstimate,
  type MotionQuality,
  gigabytes,
} from "@wasifyai/client";
import { useEffect, useState } from "react";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { Segmented } from "../components/segmented";
import { Select } from "../components/select";
import { Spinner } from "../components/spinner";
import { actions, hint, panel } from "../styles";

const QUALITIES = [
  { value: "final", label: "Make it better" },
  { value: "draft", label: "Draft 30 seconds" },
];
const LOUDEST = "loudest";

export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function minutes(seconds: number): string {
  // the web's preview of 11 stills joined in less than half a second, which read "0 seconds"
  if (seconds < 1) return "under a second";
  if (Math.round(seconds) === 1) return "1 second";
  if (seconds < 90) return `${Math.round(seconds)} seconds`;
  return `${Math.round(seconds / 60)} minutes`;
}

/** While clips are made: the time left, going by the clips this run has made. */
export function timeLeft(project: CreativeProject): string | null {
  const run = project.shots.run;
  if (run?.kind !== "motion" || !run.finished) return null;
  const clips = Object.values(project.shots.takes)
    .flat()
    .filter((t) => t.kind === "video" && t.seconds)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const last = clips.at(-1);
  if (!last) return null;
  const same = clips.filter((t) => t.mode === last.mode).slice(-12);
  const each = same.reduce((sum, t) => sum + (t.seconds ?? 0), 0) / same.length;
  return `About ${minutes(each * (run.total - run.finished))} left, going by the clips made so far.`;
}

export function MotionPanel({
  api,
  project,
  quality,
  onQuality,
  act,
}: {
  api: CreativeApi;
  project: CreativeProject;
  quality: MotionQuality;
  onQuality: (quality: MotionQuality) => void;
  act: (work: () => Promise<CreativeProject>) => Promise<void>;
}) {
  const [from, setFrom] = useState(LOUDEST);
  const [ask, setAsk] = useState<MotionEstimate | null>(null);
  const id = project.id;
  const start = quality === "draft" && from !== LOUDEST ? Number(from) : undefined;
  const clips = Object.values(project.shots.takes)
    .flat()
    .filter((t) => t.kind === "video" || t.kind === "lipsync").length;
  const stills = project.shots.missing.length;
  // biome-ignore lint/correctness/useExhaustiveDependencies: clips and stills say when the numbers changed
  useEffect(() => {
    let current = true;
    api
      .estimateMotion(id, { quality, start })
      .then((found) => current && setAsk(found))
      .catch(() => current && setAsk(null));
    return () => {
      current = false;
    };
  }, [api, id, quality, start, clips, stills]);

  const run = project.shots.run;
  const stopped = run?.kind === "motion" && run.status !== "done" && run.status !== "running";
  const none = ask?.count === 0;
  const blocked = !ask || none || !ask.ready || ask.fit === "too_big";
  const starts = [
    { value: LOUDEST, label: "The loudest part" },
    ...(ask?.sections ?? []).map((s) => ({
      value: String(s.start),
      label: `From ${clock(s.start)}${s.label ? `, ${s.label === "high" ? "loud" : s.label === "low" ? "quiet" : "middle"}` : ""}`,
    })),
  ];
  return (
    <section aria-label="Motion" className={`${panel} grid gap-3`}>
      <h2 className="m-0 font-semibold text-base">Motion</h2>
      <Segmented
        label="Which clips"
        size="sm"
        value={quality}
        onValueChange={(v) => onQuality(v as MotionQuality)}
        options={QUALITIES}
      />
      {quality === "draft" ? (
        <div className="grid gap-1">
          <span className="font-medium text-sm">Where the 30 seconds start</span>
          <Select
            aria-label="Where the 30 seconds start"
            value={from}
            onValueChange={setFrom}
            options={starts}
          />
        </div>
      ) : null}
      {!ask ? (
        <Spinner />
      ) : (
        <>
          <p className="m-0 text-sm">
            {quality === "draft"
              ? `${clock(ask.start)} to ${clock(ask.end)}: ${ask.shots} shots.`
              : `${ask.shots} ${ask.shots === 1 ? "shot is" : "shots are"} marked Animate or Sing in the plan.`}{" "}
            {none
              ? "They have their clips."
              : `${ask.count} ${ask.count === 1 ? "clip" : "clips"} to make${ask.sung ? ` (${ask.sung} ${ask.sung === 1 ? "sings" : "sing"})` : ""}, about ${minutes(ask.seconds_low)} to ${minutes(ask.seconds_high)}${ask.measured ? ", going by the clips made on this computer" : ""}, about ${gigabytes(ask.bytes)} on the disk.`}
          </p>
          <p className={`${hint} m-0`}>
            {quality === "draft"
              ? "A draft is quick and soft: a preview of the motion, not for the finished video. "
              : "Make it better is sharp and takes about four times as long as a draft. "}
            Each clip is 5 seconds, is used for its shot, and goes into Your videos; the still stays
            as another version. A shot marked Sing is lip sync instead: its face sings its part of
            the song (only the mouth moves). Stop keeps the clips made.
          </p>
          {ask.no_still ? (
            <Notice tone="info" title="Some shots have no still">
              {ask.no_still === 1 ? "1 shot has" : `${ask.no_still} shots have`} no still to start
              from, so {ask.no_still === 1 ? "it is" : "they are"} left out. Make the stills first.
            </Notice>
          ) : null}
          {ask.fit === "tight" ? (
            <Notice tone="warn" title="The disk is nearly full">
              It should fit, with little room left over.
            </Notice>
          ) : null}
          {ask.fit === "too_big" ? (
            <Notice tone="error" title="There is not enough room on the disk">
              Make room on the disk first.
            </Notice>
          ) : null}
          {ask.ready ? null : (
            <Notice tone="warn" title="A model is not ready">
              {ask.step ?? "Choose a video model with the model button on the Video tab."}
            </Notice>
          )}
        </>
      )}
      <div className={actions}>
        <Button
          type="button"
          disabled={blocked || project.shots_live || project.live}
          onClick={() => void act(() => api.makeMotion(id, { quality, start }))}
        >
          {stopped ? "Go on" : quality === "draft" ? "Draft 30 seconds" : "Make it better"}
        </Button>
      </div>
    </section>
  );
}
