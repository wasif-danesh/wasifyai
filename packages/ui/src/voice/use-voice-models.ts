"use client";

import type { AudioRuntime, VoiceApi, VoiceModelInfo, VoiceTask } from "@wasifyai/client";
import { useCallback, useEffect, useState } from "react";

/** The models for one task with their state, and the speech runtime. While the runtime is being set up
 * it looks again every second, so the dropdown changes by itself when it is done. */
export function useVoiceModels(api: VoiceApi, task: VoiceTask) {
  const [models, setModels] = useState<VoiceModelInfo[]>([]);
  const [runtime, setRuntime] = useState<AudioRuntime | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      const [list, rt] = await Promise.all([api.models(task), api.runtime()]);
      setModels(list);
      setRuntime(rt);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The models could not be listed.");
    } finally {
      setLoading(false);
    }
  }, [api, task]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const installing = runtime?.install.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const id = setInterval(() => void reload(), 1000);
    return () => clearInterval(id);
  }, [installing, reload]);

  return { models, runtime, error, loading, reload };
}
