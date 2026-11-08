"use client";

import type { TrainBase, TrainHubState, TrainingApi } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { JobMeter } from "../components/create";

const gb = (n: number) => `${(n / 1e9).toFixed(n >= 10e9 ? 0 : 1)} GB`;

/**
 * Under "Model to teach" (desktop): a model AI Toolkit loads from Hugging Face is taught only once its training
 * files are on this computer. The card says their size, gets them after the person agrees, follows the download and
 * reads the list again when it is done (`onDone`).
 */
export function HubFetch({
  api,
  base,
  onDone,
  pollMs = 2000,
}: {
  api: Pick<TrainingApi, "hubState" | "fetchHub" | "cancelHub">;
  base: TrainBase;
  onDone: () => void;
  pollMs?: number;
}) {
  const [hub, setHub] = useState<TrainHubState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  const read = useCallback(async () => {
    if (!api.hubState) return;
    try {
      const s = await api.hubState();
      setHub((was) => {
        if (was?.state === "fetching" && s.state === "done") done.current();
        return s;
      });
    } catch {
      setHub(null);
    }
  }, [api]);

  useEffect(() => {
    void read();
  }, [read]);
  const fetching = hub?.state === "fetching" && hub.base === base.id;
  useEffect(() => {
    if (!fetching) return;
    const timer = setInterval(() => void read(), pollMs);
    return () => clearInterval(timer);
  }, [fetching, read, pollMs]);

  const size = base.fetch_bytes ?? 0;
  if (!api.fetchHub || !base.can_teach || size <= 0) return null;
  const got = Math.max(0, (hub?.bytes_done ?? 0) - (hub?.bytes_start ?? 0));
  const value = fetching && size > 0 ? Math.min(1, got / size) : undefined;
  const failed = hub?.state === "error" && hub.base === base.id ? hub.error : null;
  return (
    <div className="grid gap-2">
      {fetching ? (
        <JobMeter
          title="Getting its training files"
          text={`${gb(got)} of ${gb(size)}`}
          value={value}
          label={`Download progress of the training files of ${base.title}`}
        />
      ) : null}
      {failed || error ? <span className="text-destructive text-sm">{failed || error}</span> : null}
      <div className="flex flex-wrap items-center gap-2">
        {fetching ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void api.cancelHub?.().then(setHub)}
          >
            Stop
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            onClick={async () => {
              setError(null);
              try {
                setHub((await api.fetchHub?.(base.id, size)) ?? null);
              } catch (e) {
                setError(e instanceof Error && e.message ? e.message : "It could not be started.");
              }
            }}
          >
            Get its training files ({gb(size)})
          </Button>
        )}
        <span className="text-muted-foreground text-sm">
          {base.title} is taught from its own files on Hugging Face. They are fetched once.
        </span>
      </div>
    </div>
  );
}
