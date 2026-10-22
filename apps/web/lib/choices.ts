// The model picker on the web (ADR-0086 on ADR-0087's workers): the same button and panel as the desktop window,
// over the models the engine workers list. Choosing is a remembered choice in this browser; getting a model that a
// worker lacks is an admin's action, which the worker does for itself and the panel follows.
import type { FetchJob, VoiceApi, VoiceModelInfo, WorkerInfo, WorkersApi } from "@wasifyai/client";
import {
  COPY,
  type ChoiceList,
  type ChoicesApi,
  type ChoicesSource,
  type GroupId,
  type ModelChoice,
  type Remembered,
  plainFor,
} from "@wasifyai/ui";

export type WebChoicesDeps = {
  voice: VoiceApi;
  workers: WorkersApi;
  memory: Remembered;
  /** only an admin can have a worker fetch a model */
  isAdmin: boolean;
};

/** The tasks of a group: a screen asks for one, a page of the whole group for all of them. */
export const GROUP_TASKS: Partial<Record<GroupId, string[]>> = {
  voice: ["speak", "clone", "design", "convert", "edit"],
  listening: ["transcribe"],
  music: ["music", "sfx", "separate"],
  faces: ["lipsync"],
};

export const choiceKey = (task: string) => `wasifyai.voice.model.${task}`;
const LIPSYNC_ENGINE = "lipsync-engine";
const ASK_AN_ADMIN = "Not set up on this service yet. Ask an admin to add it.";
const POLL_MS = 1500;

/** The model used when the person has not chosen: the last one that is ready, else the recommended, else any. */
export function defaultOf(models: VoiceModelInfo[], task: string, last: string | null) {
  return (
    models.find((m) => m.id === last && m.state === "ready") ??
    models.find((m) => m.recommended.includes(task as never) && m.state === "ready") ??
    models.find((m) => m.state === "ready") ??
    null
  );
}

type Engine = WorkerInfo["lipsync_engine"];

export function webRow(
  m: VoiceModelInfo,
  tasks: string[],
  chosenId: string | null,
  isAdmin: boolean,
  lipsync: Engine,
): ModelChoice {
  const needsEngine = m.engine === "sidecar" && !m.runtime_ready && m.state !== "ready";
  let state: ModelChoice["state"] = "needs_download";
  let unavailableReason: string | null = null;
  if (m.state === "ready") state = "ready";
  else if (m.state === "not_available")
    [state, unavailableReason] = ["unavailable", "Not available here"];
  else if (!m.runtime_ready && !needsEngine) {
    [state, unavailableReason] = ["unavailable", "The worker's speech engine is not set up yet."];
  } else if (needsEngine && lipsync && !lipsync.supported) {
    [state, unavailableReason] = ["unavailable", "This worker cannot run lip sync."];
  } else if (!isAdmin) [state, unavailableReason] = ["unavailable", ASK_AN_ADMIN];
  const isRecommended = tasks.some((t) => m.recommended.includes(t as never));
  const tier =
    COPY[m.id]?.tier ??
    (m.commercial_use === "no" || m.commercial_use === "unreviewed"
      ? "advanced"
      : isRecommended
        ? "recommended"
        : "also");
  const engineMissing = needsEngine && lipsync && !lipsync.installed;
  return {
    id: m.id,
    title: m.title,
    plain: plainFor(m.id, m.title),
    tier,
    state,
    chosen: m.id === chosenId,
    downloadBytes: m.state === "ready" ? 0 : m.bytes_missing,
    engineBytes: engineMissing ? lipsync.bytes : 0,
    engineName: engineMissing ? "The lip sync engine" : null,
    fit: null,
    fitReason: null,
    licence: m.licence,
    commercial: m.commercial_use,
    licenceUrl: m.licence_evidence || null,
    source: "app",
    unavailableReason,
  };
}

const pause = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal.aborted) return reject(new Error("Stopped."));
    const timer = setTimeout(() => resolve(), ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new Error("Stopped."));
      },
      { once: true },
    );
  });

/** Follow a job the worker runs on itself until it ends; `report` gets how far it is. */
async function follow(
  workers: WorkersApi,
  id: string,
  report: (job: FetchJob) => void,
  signal: AbortSignal,
): Promise<void> {
  for (;;) {
    const job = await workers.job(id);
    report(job);
    if (job.status === "done") return;
    if (job.status === "failed") throw new Error(job.error ?? "The worker could not do that.");
    if (job.status === "lost") throw new Error("The worker lost track of that. Try again.");
    await pause(POLL_MS, signal);
  }
}

export function webChoicesFor(deps: WebChoicesDeps, group: GroupId, task?: string): ChoicesApi {
  const tasks = task ? [task] : (GROUP_TASKS[group] ?? []);

  async function read() {
    const lists = await Promise.all(tasks.map((t) => deps.voice.models(t as never)));
    const models = [...new Map(lists.flat().map((m) => [m.id, m])).values()];
    const needsLipsync = models.some((m) => m.engine === "sidecar" && m.state !== "ready");
    const workers = deps.isAdmin && needsLipsync ? await deps.workers.list().catch(() => []) : [];
    const lipsync = workers.find((w) => w.lipsync_engine)?.lipsync_engine ?? null;
    return { models, lipsync };
  }

  return {
    async list(): Promise<ChoiceList> {
      const { models, lipsync } = await read();
      // one task has a model in use; the whole group shows none as in use
      const chosen = task
        ? (defaultOf(models, task, deps.memory.get(choiceKey(task)))?.id ?? null)
        : null;
      return {
        choices: models.map((m) => webRow(m, tasks, chosen, deps.isAdmin, lipsync)),
        diskFreeBytes: null,
        memoryBytes: null,
      };
    },

    async choose(id) {
      const { models } = await read();
      const m = models.find((x) => x.id === id);
      for (const t of tasks)
        if (!m || m.tasks.includes(t as never)) deps.memory.set(choiceKey(t), id);
    },

    async get(id, on, signal) {
      if (!deps.isAdmin) throw new Error(ASK_AN_ADMIN);
      const { models, lipsync } = await read();
      const m = models.find((x) => x.id === id);
      if (!m) throw new Error("That model is not in the list any more.");
      const steps: { label: string; start: () => Promise<string> }[] = [];
      if (m.engine === "sidecar" && !m.runtime_ready && lipsync && !lipsync.installed) {
        steps.push({
          label: "Setting up the lip sync engine",
          start: () => deps.workers.fetchEngine(LIPSYNC_ENGINE),
        });
      }
      if (m.state !== "ready") {
        steps.push({ label: `Getting ${m.title}`, start: () => deps.workers.fetchModel(id) });
      }
      for (const [i, step] of steps.entries()) {
        const job = await step.start();
        await follow(
          deps.workers,
          job,
          (j) => on({ label: j.label || step.label, fraction: (i + j.fraction) / steps.length }),
          signal,
        );
      }
      await this.choose(id);
    },
  };
}

/** The picker for the groups the web serves from workers (voice, listening, music, lip sync); the others have none. */
export function webChoices(deps: WebChoicesDeps): ChoicesSource {
  return (group, task) => (GROUP_TASKS[group] ? webChoicesFor(deps, group, task) : null);
}
