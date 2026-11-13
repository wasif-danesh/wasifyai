"use client";

import { useAui } from "@assistant-ui/react";
import { Button } from "../../../components/button";
import { Bar } from "../../../components/progress-bar";
import { Spinner } from "../../../components/spinner";

/**
 * A job the assistant started, while it runs (ADR-0093, stage U9): what is being made, how far (a bar when the engine
 * says), and Stop, which stops the answer and the job with it, as the box's own Stop does.
 */
export function JobProgress({
  making,
  progress,
  queued,
  place,
}: {
  /** "Making your picture" */
  making: string;
  /** 0 to 1 when the engine says */
  progress?: number;
  queued?: boolean;
  /** the place in the line while waiting */
  place?: number;
}) {
  const aui = useAui();
  const pct = typeof progress === "number" ? Math.round(progress * 100) : null;
  const text = queued
    ? place && place > 1
      ? `Waiting for a turn, place ${place}`
      : "Waiting for a turn"
    : pct !== null && pct > 0
      ? `${making}, ${pct}%`
      : making;
  return (
    <output className="grid max-w-md gap-2 rounded-lg border p-3 text-sm" data-slot="job-progress">
      <span className="flex items-center gap-3">
        <Spinner />
        <span className="min-w-0 flex-1">{text}</span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            try {
              aui.thread().cancelRun();
            } catch {
              // nothing running any more
            }
          }}
        >
          Stop
        </Button>
      </span>
      <Bar value={queued ? undefined : progress} />
    </output>
  );
}
