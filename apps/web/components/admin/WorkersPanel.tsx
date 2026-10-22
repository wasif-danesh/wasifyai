"use client";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { webWorkers } from "@/lib/library";
import { muted } from "@/lib/styles";
import type { FetchJob, WorkerInfo, WorkerModel, WorkersApi } from "@wasifyai/client";
import { formatBytes } from "@wasifyai/ui";
import { useCallback, useEffect, useRef, useState } from "react";

const POLL_MS = 2000;
const COMMERCIAL: Record<WorkerModel["commercial_use"], string> = {
  yes: "Commercial use allowed",
  conditional: "Commercial use with conditions",
  no: "Not for commercial use",
  unreviewed: "Licence not reviewed",
};

type Running = { job: string; what: string; state: FetchJob };

/** The engine workers and what each has; an admin can have a worker fetch a model or set up lip sync (ADR-0087, P5). */
export function WorkersPanel({
  initial,
  api = webWorkers,
}: { initial: WorkerInfo[]; api?: WorkersApi }) {
  const [workers, setWorkers] = useState(initial);
  const [running, setRunning] = useState<Record<string, Running>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    try {
      const next = await api.list();
      if (alive.current) setWorkers(next);
    } catch (e) {
      if (alive.current) setProblem(e instanceof Error ? e.message : "The workers did not answer.");
    }
  }, [api]);

  // follow every running job; when one ends, list the workers again so the new state shows
  useEffect(() => {
    const ids = Object.entries(running).filter(([, r]) => r.state.status === "working");
    if (ids.length === 0) return;
    const timer = setInterval(async () => {
      for (const [key, r] of ids) {
        try {
          const state = await api.job(r.job);
          if (!alive.current) return;
          setRunning((all) => ({ ...all, [key]: { ...r, state } }));
          if (state.status !== "working") await reload();
        } catch (e) {
          const error = e instanceof Error ? e.message : "The job could not be read.";
          setRunning((all) => ({
            ...all,
            [key]: { ...r, state: { status: "failed", fraction: 0, label: "", error } },
          }));
        }
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, api, reload]);

  async function start(key: string, what: string, begin: () => Promise<string>) {
    setProblem(null);
    try {
      const job = await begin();
      setRunning((all) => ({
        ...all,
        [key]: {
          job,
          what,
          state: { status: "working", fraction: 0, label: "Starting", error: null },
        },
      }));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be started.");
    }
  }

  if (workers.length === 0) {
    return (
      <output className={`${muted} block`}>
        No worker is running. Start one with <code>scripts/worker.sh start</code> (or run the worker
        image), and it appears here within a few seconds.
      </output>
    );
  }
  return (
    <div className="grid gap-6">
      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : null}
      {workers.map((w) => (
        <section key={w.id} aria-labelledby={`worker-${w.id}`} className="grid gap-3">
          <h2 id={`worker-${w.id}`} className="font-medium text-lg">
            {w.id} <span className={muted}>{w.busy ? "· busy" : "· idle"}</span>
          </h2>
          {w.lipsync_engine ? (
            <EngineRow
              worker={w}
              running={running["engine:lipsync-engine"]}
              onGet={() =>
                start("engine:lipsync-engine", "the lip sync engine", () =>
                  api.fetchEngine("lipsync-engine"),
                )
              }
            />
          ) : null}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Model</TableHead>
                <TableHead>Used for</TableHead>
                <TableHead>Licence</TableHead>
                <TableHead>On the worker</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {w.models.map((m) => (
                <ModelRow
                  key={m.id}
                  model={m}
                  canFetch={w.can_fetch}
                  running={running[`model:${m.id}`]}
                  onGet={() => start(`model:${m.id}`, m.title, () => api.fetchModel(m.id))}
                />
              ))}
            </TableBody>
          </Table>
        </section>
      ))}
    </div>
  );
}

function Progress({ running }: { running: Running }) {
  const s = running.state;
  if (s.status === "working") {
    return (
      <output className="text-sm">
        {s.label || "Working"} · {Math.round(s.fraction * 100)}%
      </output>
    );
  }
  if (s.status === "failed" || s.status === "lost") {
    return (
      <span role="alert" className="text-destructive text-sm">
        {s.error ?? "It did not finish."}
      </span>
    );
  }
  return <output className="text-sm">Done</output>;
}

function ModelRow({
  model: m,
  canFetch,
  running,
  onGet,
}: { model: WorkerModel; canFetch: boolean; running?: Running; onGet: () => void }) {
  const working = running?.state.status === "working";
  const here = m.state === "ready";
  const gettable = !here && m.state === "can_install" && canFetch && m.runtime_ready;
  return (
    <TableRow>
      <TableCell className="font-medium">{m.title}</TableCell>
      <TableCell>{m.tasks.join(", ")}</TableCell>
      <TableCell>
        {m.licence} · {COMMERCIAL[m.commercial_use]}
      </TableCell>
      <TableCell>
        {here ? (
          "Yes"
        ) : running && running.state.status !== "done" ? (
          <Progress running={running} />
        ) : gettable ? (
          <Button size="sm" variant="outline" disabled={working} onClick={onGet}>
            Get {m.title} ({formatBytes(m.bytes_missing)})
          </Button>
        ) : (
          <span className={muted}>
            {m.runtime_ready ? "Not available" : "Needs the worker's speech engine"}
          </span>
        )}
      </TableCell>
    </TableRow>
  );
}

function EngineRow({
  worker,
  running,
  onGet,
}: { worker: WorkerInfo; running?: Running; onGet: () => void }) {
  const e = worker.lipsync_engine;
  if (!e) return null;
  return (
    <p className="flex flex-wrap items-center gap-3 text-sm">
      <span className="font-medium">Lip sync engine</span>
      {e.installed ? (
        <span>Set up</span>
      ) : !e.supported ? (
        <span className={muted}>There is none for this kind of computer.</span>
      ) : running && running.state.status !== "done" ? (
        <Progress running={running} />
      ) : (
        <Button size="sm" variant="outline" onClick={onGet}>
          Set up the lip sync engine ({formatBytes(e.bytes)})
        </Button>
      )}
    </p>
  );
}
