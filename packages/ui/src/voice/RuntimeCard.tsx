"use client";

import type { AudioRuntime, VoiceApi } from "@wasifyai/client";
import { useState } from "react";
import { Button } from "../components/button";
import { Bar } from "../components/progress-bar";
import { formatBytes } from "../notebook/format";

/**
 * The speech runtime is a program of about 40 MB. Nothing is fetched by itself: this says what and how
 * big, and goes ahead on a click. A copy that another tool left on the computer can be used instead.
 */
export function RuntimeCard({
  runtime,
  api,
  onChanged,
}: {
  runtime: AudioRuntime;
  api: VoiceApi;
  onChanged: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (runtime.installed) return null;
  const { plan, install } = runtime;
  const working = install.state === "installing";
  const run = async (what: () => Promise<unknown>) => {
    setProblem(null);
    try {
      await what();
      onChanged();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That did not work.");
    }
  };

  return (
    <section aria-label="Set up speech" className="grid gap-3 rounded-2xl border bg-card p-5">
      <h2 className="font-semibold text-lg">Set up speech on this computer</h2>
      {!plan.supported ? (
        <p className="text-muted-foreground">
          There is no speech runtime for this kind of computer yet.
        </p>
      ) : (
        <>
          <p className="text-muted-foreground">
            Speech and transcription run here, with no account and nothing sent away. They need a
            small program ({formatBytes(plan.bytes)}, from the audio.cpp project, Apache-2.0).
            {plan.measured
              ? ""
              : " It has not been tested on this kind of computer, so it may be slower than expected."}
          </p>
          {working ? (
            <div className="grid gap-2">
              <Bar
                value={install.total_bytes ? install.done_bytes / install.total_bytes : undefined}
              />
              <output className="text-muted-foreground text-sm">{install.message}</output>
            </div>
          ) : asking ? (
            <div className="flex flex-wrap items-center gap-2">
              <span>Download {formatBytes(plan.bytes)} now?</span>
              <Button
                onClick={() => {
                  setAsking(false);
                  void run(() => api.installRuntime(plan.bytes));
                }}
              >
                Download
              </Button>
              <Button variant="ghost" onClick={() => setAsking(false)}>
                Not now
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => setAsking(true)}>
                Set up speech ({formatBytes(plan.bytes)})
              </Button>
              {plan.found ? (
                <Button variant="outline" onClick={() => void run(() => api.useFoundRuntime())}>
                  Use the copy already on this computer
                </Button>
              ) : null}
            </div>
          )}
        </>
      )}
      {install.state === "failed" ? (
        <p role="alert" className="text-destructive text-sm">
          {install.message}
        </p>
      ) : null}
      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : null}
    </section>
  );
}
