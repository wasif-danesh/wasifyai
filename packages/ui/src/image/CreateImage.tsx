"use client";

import type { ImageResult, RunClient } from "@wasifyai/client";
import { type ReactNode, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { FailedNotice, JobMeter, WorkingCard } from "../components/create";
import { Notice } from "../components/notice";
import { Accent, PageHero } from "../components/page-hero";
import { useImageFlow } from "../hooks/use-image-flow";
import { actions, eyebrow, panel } from "../styles";
import { ImageForm, type ImageFormValue } from "./ImageForm";

function jobText(state: ReturnType<typeof useImageFlow>["state"]): {
  text: string;
  value?: number;
} {
  const { job } = state;
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

/** What the app adds to the "image is ready" row: `primary` before "Make another", `more` after. */
export type ResultActions = { primary?: ReactNode; more?: ReactNode };

const SAVED_NOTE = "It's saved in My creations, where you can download it any time.";

export function CreateImage({
  client,
  resultActions,
  readyNote = SAVED_NOTE,
}: {
  /** The app's client (web: through its BFF; desktop: to the engine). Keep it the same object. */
  client: RunClient;
  /** Buttons around "Make another" once an image is ready: download, open in the library. */
  resultActions?: (result: ImageResult) => ResultActions;
  /** The line under "Your image is ready": where the image went. */
  readyNote?: string;
}) {
  const { state, start, reset, retry } = useImageFlow(client);
  // What the user asked for, kept so a refusal or an error can bring it back for editing.
  const [asked, setAsked] = useState<ImageFormValue | undefined>();
  const { phase } = state;
  const working = phase === "checking" || phase === "working";

  const submit = (value: ImageFormValue) => {
    setAsked(value);
    start({
      mode: value.mode,
      prompt: value.prompt,
      size: value.size,
      imageKey: value.picture?.key,
    });
  };

  const job = jobText(state);
  return (
    <>
      <div className="sr-only" aria-live="polite">
        {state.label}
      </div>

      {phase === "idle" || phase === "refused" ? (
        <>
          <PageHero
            title={
              <>
                Turn words into <Accent>an image</Accent>
              </>
            }
          >
            Describe a picture, or upload one and say what to change.
          </PageHero>
          {phase === "refused" && state.refusal ? (
            <Notice tone="warn" title="We can't make that one">
              {state.refusal.message}
            </Notice>
          ) : null}
          <ImageForm client={client} onSubmit={submit} initial={asked} />
        </>
      ) : (
        <>
          {asked ? (
            <section className={panel} aria-label="Your request">
              <span className={eyebrow}>{asked.mode === "image" ? "Your edit" : "Your idea"}</span>
              <p>{asked.prompt}</p>
            </section>
          ) : null}

          {working ? (
            <WorkingCard label={state.label || "Working"} onCancel={reset}>
              {phase === "working" ? (
                <JobMeter
                  title="Painting your image"
                  text={job.text}
                  value={job.value}
                  label="Image progress"
                />
              ) : null}
            </WorkingCard>
          ) : null}

          {phase === "done" && state.result ? (
            <>
              <Notice tone="ok" title="Your image is ready">
                {readyNote}
              </Notice>
              <figure className={cn(panel, "m-0 justify-items-center")}>
                <img
                  className="h-auto max-w-full rounded-xl shadow-card"
                  src={state.result.imageUrl}
                  alt={state.result.prompt}
                  width={state.result.width || undefined}
                  height={state.result.height || undefined}
                />
              </figure>
              <div className={actions}>
                {resultActions?.(state.result).primary}
                <Button type="button" variant="outline" onClick={reset}>
                  Make another
                </Button>
                {resultActions?.(state.result).more}
              </div>
            </>
          ) : null}

          {phase === "error" && state.error ? (
            <FailedNotice
              message={state.error.message}
              retryable={state.error.retryable}
              onRetry={retry}
              onReset={reset}
            />
          ) : null}
        </>
      )}
    </>
  );
}
