"use client";

import type { TrainingApi, VideoTrainStatus } from "@wasifyai/client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTrainingSetup } from "./use-setup";

/**
 * Teaching the video model (ADR-0073, video amendment): whether it can be done on this computer, and the
 * video trainer's own setup, read the same way as the other trainers'. Where the engine has no video trainer
 * (the web), the status stays null and the screen offers nothing.
 */
export function useVideoTraining(
  api: TrainingApi,
  enabled: boolean,
  /** changes whenever the screen read training again: the status is read with it */
  stamp: unknown,
  pollMs = 1500,
) {
  const [status, setStatus] = useState<VideoTrainStatus | null>(null);
  const read = useCallback(async () => {
    try {
      setStatus(await api.videoStatus());
    } catch {
      setStatus(null);
    }
  }, [api]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: `stamp` is the signal to read again
  useEffect(() => {
    if (enabled) void read();
  }, [enabled, read, stamp]);

  const adapter = useMemo(
    () => ({
      setup: api.videoSetup,
      installSetup: api.installVideoSetup,
      cancelSetup: api.cancelVideoSetup,
      removeSetup: api.removeVideoSetup,
    }),
    [api],
  );
  const setup = useTrainingSetup(adapter, enabled, () => void read(), pollMs);
  return { status, setup, reload: read };
}

export type VideoTraining = ReturnType<typeof useVideoTraining>;
