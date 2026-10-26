"use client";

import { type TrainingSetupState, gigabytes } from "@wasifyai/client";
import { Button } from "../components/button";
import { JobMeter, WorkingCard } from "../components/create";
import { Notice } from "../components/notice";
import { actions, hint, panel } from "../styles";

/**
 * "Set up training": the trainer and the picture model it learns on are not in the app. What will be fetched, how
 * large, whose licence and from where is shown first; nothing is fetched until the button is pressed, and the button
 * repeats the size. A set up that stops continues where it stopped.
 */
export function SetupCard({
  setup,
  error,
  onInstall,
  onCancel,
  intro,
  title = "Set up training",
}: {
  setup: TrainingSetupState;
  error: string | null;
  onInstall: (bytes: number) => void;
  onCancel: () => void;
  /** what is being set up, in a sentence: the picture trainer's by default */
  intro?: string;
  title?: string;
}) {
  const { plan, progress } = setup;
  const installing = progress.state === "installing";
  const value = progress.total_bytes > 0 ? progress.done_bytes / progress.total_bytes : undefined;
  const parts = plan.parts.filter((p) => !p.have || p.bytes > 0);
  return (
    <section className={panel} aria-label={title}>
      <h2 className="m-0 font-semibold text-lg">{title}</h2>
      <p className="m-0 text-muted-foreground">
        {intro ??
          "Teaching a picture model needs a trainer and the picture model it learns on. They are not in the app. They are downloaded once, every file checked, and kept in the app's own folder. Nothing else on your computer is changed, and your pictures are not sent anywhere."}
      </p>
      <ul className="m-0 grid list-none gap-1.5 p-0">
        {plan.parts.map((p) => (
          <li key={p.name} className="flex flex-wrap justify-between gap-x-4">
            <span>
              <strong>{p.name}</strong> <span className="text-muted-foreground">{p.version}</span>
            </span>
            <span className="text-muted-foreground tabular-nums">
              {p.have ? "Already on this computer" : `${gigabytes(p.bytes)}`} · {p.licence} · from{" "}
              {p.source}
            </span>
          </li>
        ))}
      </ul>
      <p className={hint}>
        You need about {gigabytes(plan.needs_free_bytes)} of free disk space. It continues where it
        stopped if it is interrupted. You can remove it again later.
      </p>
      {installing ? (
        <WorkingCard label={progress.message || "Setting up"} onCancel={onCancel}>
          <JobMeter
            title="Setting up training"
            text={value === undefined ? "Starting" : `${Math.round(value * 100)}%`}
            value={value}
            label="Setup progress"
          />
        </WorkingCard>
      ) : (
        <div className={actions}>
          <Button
            type="button"
            size="lg"
            disabled={parts.length === 0}
            onClick={() => onInstall(plan.bytes)}
          >
            Download and set up ({gigabytes(plan.bytes)})
          </Button>
        </div>
      )}
      {progress.state === "failed" ? (
        <Notice tone="error" title="Setting up did not finish">
          {progress.message}
        </Notice>
      ) : null}
      {error ? (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      ) : null}
    </section>
  );
}
