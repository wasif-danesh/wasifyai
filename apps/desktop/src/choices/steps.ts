// SPDX-License-Identifier: AGPL-3.0-only
// "Get and use" as steps (ADR-0086): an engine, then the model's files, each reporting how far it is. The steps
// share one progress bar, weighted by their size, and stop when the person presses Stop.
import type { GetProgress } from "@wasifyai/ui";
import { type ModelEntry, type ModelsApi, downloadFraction } from "../models";

export type Step = {
  label: string;
  /** about how many bytes this step moves: its share of the bar (1 when not known) */
  bytes: number;
  run(report: (fraction: number, label?: string) => void, signal: AbortSignal): Promise<void>;
};

/** Wait, but not past a Stop. */
export function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        resolve();
      },
      { once: true },
    );
  });
}

export async function runSteps(
  steps: Step[],
  on: (p: GetProgress) => void,
  signal: AbortSignal,
): Promise<void> {
  const weights = steps.map((s) => Math.max(1, s.bytes));
  const total = weights.reduce((a, b) => a + b, 0);
  let done = 0;
  for (const [i, step] of steps.entries()) {
    if (signal.aborted) throw new Error("Stopped.");
    on({ label: step.label, fraction: done / total });
    await step.run((fraction, label) => {
      on({
        label: label ?? step.label,
        fraction: (done + Math.min(1, Math.max(0, fraction)) * (weights[i] as number)) / total,
      });
    }, signal);
    if (signal.aborted) throw new Error("Stopped.");
    done += weights[i] as number;
  }
  on({ label: "Done", fraction: 1 });
}

/** The model's own files, through the confirm-first download the engine already has (ADR-0059). */
export function modelStep(
  models: ModelsApi,
  entry: ModelEntry,
  opts: { acceptMemory?: boolean; pollMs?: number } = {},
): Step {
  return {
    label: `Downloading ${entry.title}`,
    bytes: entry.bytes_missing,
    async run(report, signal) {
      const started = await models.start(entry, opts.acceptMemory ?? false);
      const stop = () => void models.cancel(started.id).catch(() => {});
      signal.addEventListener("abort", stop, { once: true });
      try {
        for (;;) {
          const d = await models.download(started.id);
          report(downloadFraction(d));
          if (d.status === "done") return;
          if (d.status === "failed") throw new Error(d.error || "The download failed.");
          if (d.status === "cancelled") throw new Error("Stopped.");
          if (signal.aborted) throw new Error("Stopped.");
          await pause(opts.pollMs ?? 1000, signal);
        }
      } finally {
        signal.removeEventListener("abort", stop);
      }
    },
  };
}
