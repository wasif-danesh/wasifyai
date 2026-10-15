"use client";

import { Notice } from "@/components/Notice";
import { FailedNotice, WorkingCard } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { Accent, PageHero } from "@/components/ui/page-hero";
import { Spinner } from "@/components/ui/spinner";
import { STARTED_EVENT } from "@/hooks/use-video-activity";
import { useVideoFlow } from "@/hooks/use-video-flow";
import { actions, eyebrow, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useEffect, useState } from "react";
import { VideoForm, type VideoFormValue } from "./VideoForm";

export function CreateVideo() {
  const { state, start, reset, retry } = useVideoFlow();
  // What the user asked for, kept so a refusal or an error can bring it back for editing.
  const [asked, setAsked] = useState<VideoFormValue | undefined>();
  const { phase } = state;

  // Tell the header a clip is being made, so its badge shows up at once on every page.
  useEffect(() => {
    if (phase === "making") window.dispatchEvent(new Event(STARTED_EVENT));
  }, [phase]);

  const submit = (value: VideoFormValue) => {
    setAsked(value);
    start({
      mode: value.mode,
      prompt: value.prompt,
      shape: value.shape,
      seconds: value.seconds,
      imageKey: value.picture?.key,
    });
  };

  const minutes = asked?.seconds === 5 ? "about 8 minutes" : "about 3 minutes";

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
                Bring a scene to <Accent>life</Accent>
              </>
            }
          >
            Describe a scene, or upload a picture and say what should move.
          </PageHero>
          {phase === "refused" && state.refusal ? (
            <Notice tone="warn" title="We can't make that one">
              {state.refusal.message}
            </Notice>
          ) : null}
          <VideoForm onSubmit={submit} initial={asked} />
        </>
      ) : (
        <>
          {asked ? (
            <section className={panel} aria-label="Your request">
              <span className={eyebrow}>
                {asked.mode === "image" ? "Your picture, brought to life" : "Your scene"} ·{" "}
                {asked.seconds} seconds
              </span>
              <p>{asked.prompt}</p>
            </section>
          ) : null}

          {phase === "checking" ? (
            <WorkingCard label={state.label || "Checking your request"} onCancel={reset} />
          ) : null}

          {phase === "making" ? (
            <section className={panel} aria-label="Your video is being made">
              <div className="flex items-center gap-[0.8rem] font-semibold">
                <Spinner />
                <strong>Your video is being created</strong>
              </div>
              <p>
                This takes {minutes}. You don't have to wait here: explore the site and we'll tell
                you when it's ready. It will also be in My creations.
              </p>
              <p className="text-muted-foreground">
                {state.job.status === "queued"
                  ? state.job.position && state.job.position > 1
                    ? `In line, place ${state.job.position}.`
                    : "You're next."
                  : state.job.status === "running" && (state.job.progress ?? 0) > 0
                    ? `${Math.round((state.job.progress ?? 0) * 100)}% done.`
                    : "Getting started."}
              </p>
              <div className={actions}>
                <Button asChild>
                  <Link href="/creations">Go to My creations</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/">Explore Wasify AI</Link>
                </Button>
              </div>
            </section>
          ) : null}

          {phase === "done" && state.result ? (
            <>
              <Notice tone="ok" title="Your video is ready">
                It's saved in My creations, where you can watch and download it any time.
              </Notice>
              <figure className={cn(panel, "m-0 justify-items-center")}>
                {/* biome-ignore lint/a11y/useMediaCaption: generated clips have no speech to caption */}
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
                {state.result.videoId ? (
                  <Button asChild>
                    <a
                      href={`/api/products/wasifyai-video/videos/${state.result.videoId}/download`}
                      download
                    >
                      Download
                    </a>
                  </Button>
                ) : null}
                <Button type="button" variant="outline" onClick={reset}>
                  Make another
                </Button>
                {state.result.videoId ? (
                  <Button asChild variant="outline">
                    <Link href={`/video/creations/${state.result.videoId}`}>
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
