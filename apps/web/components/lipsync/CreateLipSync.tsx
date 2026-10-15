"use client";

import { Notice } from "@/components/Notice";
import { FailedNotice, WorkingCard } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { Accent, PageHero } from "@/components/ui/page-hero";
import { Spinner } from "@/components/ui/spinner";
import { STARTED_EVENT } from "@/hooks/use-lipsync-activity";
import { useLipSyncFlow } from "@/hooks/use-lipsync-flow";
import { actions, eyebrow, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { VoiceCatalog } from "@wasifyai/contracts";
import Link from "next/link";
import { useEffect, useState } from "react";
import { LipSyncForm, type LipSyncFormValue } from "./LipSyncForm";

export function CreateLipSync({ catalog }: { catalog: VoiceCatalog }) {
  const { state, start, reset, retry } = useLipSyncFlow();
  // What the user asked for, kept so a refusal or an error can bring it back for editing.
  const [asked, setAsked] = useState<LipSyncFormValue | undefined>();
  const { phase } = state;

  // Tell the header a lip sync is being made, so its badge shows up at once on every page.
  useEffect(() => {
    if (phase === "making") window.dispatchEvent(new Event(STARTED_EVENT));
  }, [phase]);

  const submit = (value: LipSyncFormValue) => {
    setAsked(value);
    start({
      source: value.source,
      imageKey: value.picture.key,
      audioKey: value.audioKey,
      script: value.script,
      language: value.language,
      gender: value.gender,
      style: value.style,
    });
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
                Give a character a <Accent>voice</Accent>
              </>
            }
          >
            Add a picture of a character and a voice, a song or a script, and watch it speak or sing
            in sync.
          </PageHero>
          {phase === "refused" && state.refusal ? (
            <Notice tone="warn" title="We can't make that one">
              {state.refusal.message}
            </Notice>
          ) : null}
          <LipSyncForm
            catalog={catalog}
            onSubmit={submit}
            initial={
              asked
                ? {
                    script: asked.script,
                    language: asked.language,
                    gender: asked.gender,
                    style: asked.style,
                  }
                : undefined
            }
          />
        </>
      ) : (
        <>
          {asked ? (
            <section className={panel} aria-label="Your request">
              <span className={eyebrow}>
                {asked.source === "script" ? "Your script" : "Your voice"}
              </span>
              {asked.script ? <p>{asked.script}</p> : null}
            </section>
          ) : null}

          {phase === "checking" ? (
            <WorkingCard label={state.label || "Checking your request"} onCancel={reset} />
          ) : null}

          {phase === "making" ? (
            <section className={panel} aria-label="Your lip sync is being made">
              <div className="flex items-center gap-[0.8rem] font-semibold">
                <Spinner />
                <strong>Your lip sync is being created</strong>
              </div>
              <p>
                This can take a while. You don't have to wait here: explore the site and we'll tell
                you when it's ready. It will also be in My creations.
              </p>
              <p className="text-muted-foreground">
                {state.label ? `${state.label}. ` : ""}
                {state.job.status === "queued"
                  ? state.job.position && state.job.position > 1
                    ? `In line, place ${state.job.position}.`
                    : "You're next."
                  : state.job.status === "running" && (state.job.progress ?? 0) > 0
                    ? `${Math.round((state.job.progress ?? 0) * 100)}% done.`
                    : ""}
              </p>
              <div className={actions}>
                <Button asChild>
                  <Link href="/creations?show=lipsyncs">Go to My creations</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/">Explore Wasify AI</Link>
                </Button>
              </div>
            </section>
          ) : null}

          {phase === "done" && state.result ? (
            <>
              <Notice tone="ok" title="Your lip sync is ready">
                It's saved in My creations, where you can watch and download it any time.
              </Notice>
              <figure className={cn(panel, "m-0 justify-items-center")}>
                {/* biome-ignore lint/a11y/useMediaCaption: the clip carries its own voice */}
                <video
                  className="h-auto max-h-[70vh] max-w-full rounded-xl bg-black shadow-card"
                  controls
                  playsInline
                  preload="metadata"
                  poster={state.result.posterUrl || undefined}
                  src={state.result.videoUrl}
                />
              </figure>
              <div className={actions}>
                {state.result.lipsyncId ? (
                  <Button asChild>
                    <a
                      href={`/api/products/wasifyai-lipsync/lipsyncs/${state.result.lipsyncId}/download`}
                      download
                    >
                      Download
                    </a>
                  </Button>
                ) : null}
                <Button type="button" variant="outline" onClick={reset}>
                  Make another
                </Button>
                {state.result.lipsyncId ? (
                  <Button asChild variant="outline">
                    <Link href={`/lip-sync/creations/${state.result.lipsyncId}`}>
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
