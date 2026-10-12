"use client";

import type { LipSyncSummary } from "@wasifyai/contracts";
import { BURST_FOR_MS, BURST_MS, type Outcome, POLL_MS, useWorkingActivity } from "./use-activity";

export { BURST_FOR_MS, BURST_MS, POLL_MS };
export type { Outcome };
export const STARTED_EVENT = "wasifyai:lipsync-started";

const CONFIG = {
  product: "wasifyai-lipsync",
  collection: "lipsyncs",
  label: (v: LipSyncSummary) => v.text || "Lip sync",
  startedEvent: STARTED_EVENT,
};

/** The lip syncs being made, and the notice when one finishes (ADR-0044). */
export function useLipSyncActivity(enabled: boolean) {
  return useWorkingActivity<LipSyncSummary>(CONFIG, enabled);
}
