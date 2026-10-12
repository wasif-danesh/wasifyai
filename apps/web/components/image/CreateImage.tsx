"use client";

import { Notice } from "@/components/Notice";
import { FailedNotice, JobMeter, WorkingCard } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { Accent, PageHero } from "@/components/ui/page-hero";
import { useImageFlow } from "@/hooks/use-image-flow";
import { actions, eyebrow, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useState } from "react";
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

export function CreateImage() {
  const { state, start, reset, retry } = useImageFlow();
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
          <ImageForm onSubmit={submit} initial={asked} />
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
                It's saved in My creations, where you can download it any time.
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
                {state.result.imageId ? (
                  <Button asChild>
                    <a
                      href={`/api/products/wasifyai-image/images/${state.result.imageId}/download`}
                      download
                    >
                      Download
                    </a>
                  </Button>
                ) : null}
                <Button type="button" variant="outline" onClick={reset}>
                  Make another
                </Button>
                {state.result.imageId ? (
                  <Button asChild variant="outline">
                    <Link href={`/image/creations/${state.result.imageId}`}>
                      Open in My creations
                    </Link>
                  </Button>
                ) : null}
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
