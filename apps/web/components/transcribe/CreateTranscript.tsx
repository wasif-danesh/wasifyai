"use client";

import { Notice } from "@/components/Notice";
import { FailedNotice, WorkingCard } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { Accent, PageHero } from "@/components/ui/page-hero";
import { Spinner } from "@/components/ui/spinner";
import { TRANSCRIPT_STARTED_EVENT } from "@/hooks/use-activity";
import { useTranscriptFlow } from "@/hooks/use-transcript-flow";
import { clock } from "@/lib/format";
import { actions, panel } from "@/lib/styles";
import type { SpokenLanguages } from "@wasifyai/contracts";
import Link from "next/link";
import { useEffect, useState } from "react";
import { TranscribeForm, type TranscribeFormValue } from "./TranscribeForm";

export function CreateTranscript({ catalog }: { catalog: SpokenLanguages }) {
  const { state, start, reset, retry } = useTranscriptFlow();
  // What the user asked for, kept so a refusal or an error can bring it back for editing.
  const [asked, setAsked] = useState<TranscribeFormValue | undefined>();
  const { phase } = state;

  // Tell the top bar something is being made, so its badge shows up at once on every page.
  useEffect(() => {
    if (phase === "making") window.dispatchEvent(new Event(TRANSCRIPT_STARTED_EVENT));
  }, [phase]);

  const submit = (value: TranscribeFormValue) => {
    setAsked(value);
    start(value);
  };

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
                Turn speech into <Accent>text</Accent>
              </>
            }
          >
            Upload a recording or a video, or record your voice, and get a transcript with
            timestamps.
          </PageHero>
          {phase === "refused" && state.refusal ? (
            <Notice tone="warn" title="We can't transcribe that one">
              {state.refusal.message}
            </Notice>
          ) : null}
          <TranscribeForm catalog={catalog} onSubmit={submit} initial={asked} />
        </>
      ) : (
        <>
          {phase === "checking" ? (
            <WorkingCard label={state.label || "Checking your recording"} onCancel={reset} />
          ) : null}

          {phase === "making" ? (
            <section className={panel} aria-label="Your recording is being transcribed">
              <div className="flex items-center gap-[0.8rem] font-semibold">
                <Spinner />
                <strong>Your recording is being transcribed</strong>
              </div>
              <p>
                This can take a few minutes for a long recording. You don't have to wait here:
                explore the site and we'll tell you when it's ready. It will also be in My
                creations.
              </p>
              <p className="text-muted-foreground">
                {state.job.status === "queued"
                  ? state.job.position && state.job.position > 1
                    ? `In line, place ${state.job.position}.`
                    : "You're next."
                  : state.job.status === "running" && (state.job.progress ?? 0) > 0.15
                    ? `${Math.round((state.job.progress ?? 0) * 100)}% done.`
                    : "Getting started."}
              </p>
              <div className={actions}>
                <Button asChild>
                  <Link href="/creations?show=transcripts">Go to My creations</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/">Explore Wasify AI</Link>
                </Button>
              </div>
            </section>
          ) : null}

          {phase === "done" && state.result ? (
            <>
              <Notice tone="ok" title="Your transcript is ready">
                {state.result.title} · {clock(state.result.seconds)}. It's saved in My creations.
              </Notice>
              <div className={actions}>
                <Button asChild>
                  <Link href={`/speech-to-text/creations/${state.result.transcriptId}`}>
                    Read the transcript
                  </Link>
                </Button>
                <Button type="button" variant="outline" onClick={reset}>
                  Transcribe another
                </Button>
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
