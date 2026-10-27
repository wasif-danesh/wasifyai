"use client";

import { webWorkers } from "@/lib/library";
import { muted } from "@/lib/styles";
import type { WorkerInfo } from "@wasifyai/client";
import { Button } from "@wasifyai/ui";
import { useCallback, useEffect, useState } from "react";

/** What a trainer needs to be set up from here: the component a worker lists, and the name of its set-up job. */
type Engine = "video-trainer" | "image-trainer";
const TRAINERS: { component: string; engine: Engine; title: string }[] = [
  { component: "train.video", engine: "video-trainer", title: "Video model training" },
  { component: "train.image", engine: "image-trainer", title: "Image model training" },
];

const size = (bytes: number | undefined) =>
  bytes === undefined || bytes <= 0
    ? ""
    : ` (${bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`})`;

type Working = { label: string; fraction: number } | { error: string } | null;

/** Train models on the web: each worker lists the trainers it can run; an admin sets one up on the worker (the same card as the desktop's, its size shown first). */
export function TrainersAdmin({ workers }: { workers: WorkerInfo[] }) {
  const [state, setState] = useState<Record<string, Working>>({});
  const [list, setList] = useState(workers);
  const reload = useCallback(async () => setList(await webWorkers.list()), []);
  useEffect(() => setList(workers), [workers]);

  async function setUp(engine: Engine) {
    try {
      const id = await webWorkers.fetchEngine(engine);
      for (;;) {
        const job = await webWorkers.job(id);
        if (job.status === "working") {
          setState((s) => ({ ...s, [engine]: { label: job.label, fraction: job.fraction } }));
          await new Promise((r) => setTimeout(r, 1500));
          continue;
        }
        setState((s) => ({
          ...s,
          [engine]: job.status === "done" ? null : { error: job.error ?? "It did not finish." },
        }));
        break;
      }
      await reload();
    } catch (e) {
      setState((s) => ({
        ...s,
        [engine]: { error: e instanceof Error ? e.message : "It could not be started." },
      }));
    }
  }

  const rows = TRAINERS.flatMap((t) =>
    list
      .filter((w) => t.component in w.components)
      .map((w) => ({ t, w, c: w.components[t.component] })),
  );
  return (
    <section aria-label="Trainers" className="grid gap-2">
      <h2 className="m-0 font-semibold text-lg">Trainers</h2>
      <p className={muted}>
        Teaching a model of someone's own runs on a worker. Set a trainer up once; people can then
        teach that kind of model from Train models.
      </p>
      {rows.length === 0 ? (
        <output className={`${muted} block`}>No worker lists a trainer yet.</output>
      ) : (
        <ul className="m-0 grid list-none gap-2 p-0 text-sm">
          {rows.map(({ t, w, c }) => {
            const s = state[t.engine];
            return (
              <li key={`${w.id}-${t.component}`} className="flex flex-wrap items-center gap-3">
                <span className="font-medium">{t.title}</span>
                <span className={muted}>on {w.id}</span>
                {c?.ready ? (
                  <span>Ready</span>
                ) : (
                  <>
                    <span className={muted}>{c?.problem ?? "Not set up"}</span>
                    {s && "label" in s ? (
                      <output>
                        {s.label || "Setting up"} {Math.round(s.fraction * 100)}%
                      </output>
                    ) : (
                      <Button type="button" size="sm" onClick={() => void setUp(t.engine)}>
                        Set up{size(c?.setup?.bytes)}
                      </Button>
                    )}
                    {s && "error" in s ? <span role="alert">{s.error}</span> : null}
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
