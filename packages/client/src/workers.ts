// The engine workers, for admins (ADR-0087, P5): which workers are running, which models each has,
// and getting a model (or the lip sync engine) onto a worker. A fetch is a job the worker runs on
// itself; the page follows it by its id.
import { HttpError, type Transport, errorMessage } from "./transport";

export type WorkerModel = {
  id: string;
  title: string;
  /** `ready` is on the worker; `can_install` needs a fetch; others cannot be fetched */
  state: string;
  bytes_missing: number;
  licence: string;
  commercial_use: "yes" | "conditional" | "no" | "unreviewed";
  tasks: string[];
  engine: string;
  runtime_ready: boolean;
};

export type WorkerInfo = {
  id: string;
  busy: boolean;
  seen: number;
  can_fetch: boolean;
  models: WorkerModel[];
  lipsync_engine: { installed: boolean; supported: boolean; bytes: number } | null;
  components: Record<
    string,
    {
      ready?: boolean;
      problem?: string | null;
      /** what setting it up would fetch (a trainer): its size, and whether this computer can run it */
      setup?: { supported: boolean; bytes: number } | null;
    }
  >;
};

export type FetchJob = {
  status: "working" | "done" | "failed" | "lost";
  fraction: number;
  label: string;
  error: string | null;
};

export type WorkersApi = {
  list(): Promise<WorkerInfo[]>;
  /** Start getting a model onto a worker; the id of the job to follow. */
  fetchModel(modelId: string): Promise<string>;
  fetchEngine(name: "lipsync-engine" | "video-trainer" | "image-trainer"): Promise<string>;
  job(id: string): Promise<FetchJob>;
};

export function createWorkersApi(transport: Transport): WorkersApi {
  const base = "/admin/workers";
  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }
  const started = async (path: string) =>
    (await json<{ job_id: string }>(path, { method: "POST" })).job_id;
  return {
    list: async () => (await json<{ workers: WorkerInfo[] }>(base)).workers,
    fetchModel: (id) => started(`${base}/models/${encodeURIComponent(id)}/fetch`),
    fetchEngine: (name) => started(`${base}/engines/${encodeURIComponent(name)}/fetch`),
    job: async (id) => {
      const s = await json<Partial<FetchJob> & { status: FetchJob["status"] }>(
        `${base}/jobs/${encodeURIComponent(id)}`,
      );
      return { fraction: 0, label: "", error: null, ...s };
    },
  };
}
