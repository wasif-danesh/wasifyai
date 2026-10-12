"use client";

import { Notice } from "@/components/Notice";
import { FailedNotice, WorkingCard } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { Accent, PageHero } from "@/components/ui/page-hero";
import { useSpeechFlow } from "@/hooks/use-speech-flow";
import { actions, eyebrow, panel, player } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { VoiceCatalog } from "@wasifyai/contracts";
import Link from "next/link";
import { useState } from "react";
import { SpeechForm, type SpeechFormValue } from "./SpeechForm";

export function CreateSpeech({ catalog }: { catalog: VoiceCatalog }) {
  const { state, start, reset, retry } = useSpeechFlow();
  // What the user asked for, kept so a refusal or an error can bring it back for editing.
  const [asked, setAsked] = useState<SpeechFormValue | undefined>();
  const { phase } = state;
  const working = phase === "checking" || phase === "working";

  const submit = (value: SpeechFormValue) => {
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
                Turn text into <Accent>speech</Accent>
              </>
            }
          >
            Type or paste your text, choose a language and a voice, and listen.
          </PageHero>
          {phase === "refused" && state.refusal ? (
            <Notice tone="warn" title="We can't make that one">
              {state.refusal.message}
            </Notice>
          ) : null}
          <SpeechForm catalog={catalog} onSubmit={submit} initial={asked} />
        </>
      ) : (
        <>
          {asked ? (
            <section className={panel} aria-label="Your text">
              <span className={eyebrow}>Your text</span>
              <p lang={asked.language}>{asked.text}</p>
            </section>
          ) : null}

          {working ? <WorkingCard label={state.label || "Working"} onCancel={reset} /> : null}

          {phase === "done" && state.result ? (
            <>
              <Notice tone="ok" title="Your speech is ready">
                It's saved in My creations, where you can listen and download it any time.
              </Notice>
              <figure className={cn(panel, "m-0 gap-[0.6rem]")}>
                <figcaption className="text-muted-foreground">
                  {state.result.voice} · {Math.round(state.result.seconds)} seconds
                </figcaption>
                {/* biome-ignore lint/a11y/useMediaCaption: the text that is spoken is shown above */}
                <audio controls preload="auto" src={state.result.audioUrl} className={player}>
                  Your browser can't play this audio.
                </audio>
              </figure>
              <div className={actions}>
                {state.result.speechId ? (
                  <Button asChild>
                    <a
                      href={`/api/products/wasifyai-tts/speeches/${state.result.speechId}/download`}
                      download
                    >
                      Download MP3
                    </a>
                  </Button>
                ) : null}
                <Button type="button" variant="outline" onClick={reset}>
                  Make another
                </Button>
                {state.result.speechId ? (
                  <Button asChild variant="outline">
                    <Link href={`/text-to-speech/creations/${state.result.speechId}`}>
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
