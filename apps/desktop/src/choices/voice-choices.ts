// SPDX-License-Identifier: AGPL-3.0-only
// The picker's rows and work for the speech, listening, music and lip sync groups (ADR-0086), from the voice
// engine's model list, the catalogue (fit, size) and the engines a model runs on.
import type { AudioRuntime, LipSyncEngine, VoiceApi, VoiceModelInfo } from "@wasifyai/client";
import type { ChoiceList, ChoicesApi, GroupId, ModelChoice } from "@wasifyai/ui";
import type { ModelEntry, ModelsApi } from "../models";
import { removable } from "./catalogue-choices";
import { COPY, hostOf, plainFor } from "./copy";
import { type Step, modelStep, pause, runSteps } from "./steps";
import type { Engines, Memory } from "./types";

export type VoiceChoicesDeps = {
  voice: VoiceApi;
  models: ModelsApi;
  memory: Memory;
  engines: Engines;
};

type Context = {
  runtime: AudioRuntime | null;
  lipsync: LipSyncEngine | null;
  image: { installed: boolean; bytes: number };
  entries: Map<string, ModelEntry>;
};

export const choiceKey = (task: string) => `wasifyai.voice.model.${task}`;

/** The tasks of a group: a screen asks for one, the Models page for all of them. */
export const GROUP_TASKS: Record<string, string[]> = {
  voice: ["speak", "clone", "design", "convert", "edit"],
  listening: ["transcribe"],
  music: ["music", "sfx", "separate"],
  faces: ["lipsync"],
};

/** The model used when the person has not chosen: the recommended one that is ready, else any that is ready. */
export function defaultOf(models: VoiceModelInfo[], task: string, last: string | null) {
  return (
    models.find((m) => m.id === last && m.state === "ready") ??
    models.find((m) => m.recommended.includes(task as never) && m.state === "ready") ??
    models.find((m) => m.state === "ready") ??
    null
  );
}

/** One model as a row: its state, what must be downloaded (the engine and the files) and its fit. */
export function voiceRow(
  m: VoiceModelInfo,
  tasks: string[],
  ctx: Context,
  chosenId: string | null,
): ModelChoice {
  const isRecommended = tasks.some((t) => m.recommended.includes(t as never));
  const entry = ctx.entries.get(m.id);
  const fit = entry?.fit?.verdict ?? null;
  let engineBytes = 0;
  let engineName: string | null = null;
  if (m.state !== "ready" && !m.runtime_ready) {
    if (m.engine === "comfyui") {
      if (!ctx.image.installed) [engineBytes, engineName] = [ctx.image.bytes, "The image engine"];
    } else if (m.engine === "sidecar") {
      if (ctx.lipsync && !ctx.lipsync.installed) {
        [engineBytes, engineName] = [ctx.lipsync.plan.bytes, "The lip sync engine"];
      }
    } else if (ctx.runtime && !ctx.runtime.installed) {
      [engineBytes, engineName] = [ctx.runtime.plan.bytes, "The speech engine"];
    }
  }
  const state: ModelChoice["state"] =
    m.state === "ready"
      ? "ready"
      : m.state === "not_available"
        ? "unavailable"
        : fit === "too_big"
          ? "too_big"
          : "needs_download";
  const tier = COPY[m.id]?.tier ?? (isRecommended ? "recommended" : "also");
  return {
    id: m.id,
    title: m.title,
    plain: plainFor(m.id, m.title),
    tier,
    state,
    chosen: m.id === chosenId,
    downloadBytes: m.state === "ready" ? 0 : m.bytes_missing,
    engineBytes,
    engineName,
    fit,
    fitReason: entry?.fit?.reason ?? null,
    source: "app",
    from: hostOf(entry?.source),
    sizeBytes: entry && state === "ready" ? entry.bytes_total : 0,
    removable: entry ? removable(entry) : false,
    unavailableReason: state === "unavailable" ? "Not available on this computer" : null,
  };
}

async function read(deps: VoiceChoicesDeps, tasks: string[]) {
  const [lists, runtime, overview, image] = await Promise.all([
    Promise.all(tasks.map((t) => deps.voice.models(t as never))),
    deps.voice.runtime().catch(() => null),
    deps.models.overview().catch(() => null),
    deps.engines.image().catch(() => ({ installed: true, supported: false, bytes: 0, name: "" })),
  ]);
  const models = [...new Map(lists.flat().map((m) => [m.id, m])).values()];
  const needsLipsync = models.some((m) => m.engine === "sidecar" && m.state !== "ready");
  const lipsync = needsLipsync ? await deps.voice.lipsyncEngine().catch(() => null) : null;
  const ctx: Context = {
    runtime,
    lipsync,
    image,
    entries: new Map((overview?.models ?? []).map((e) => [e.id, e])),
  };
  return { models, ctx, overview };
}

async function pollInstall(
  poll: () => Promise<{
    install: { state: string; message: string; done_bytes: number; total_bytes: number };
  }>,
  report: (fraction: number, label?: string) => void,
  signal: AbortSignal,
): Promise<void> {
  for (;;) {
    const s = (await poll()).install;
    const fraction = s.total_bytes > 0 ? s.done_bytes / s.total_bytes : 0;
    report(fraction, s.message || undefined);
    if (s.state === "ready") return;
    if (s.state === "failed") throw new Error(s.message || "The setup did not finish.");
    if (signal.aborted) throw new Error("Stopped.");
    await pause(1000, signal);
  }
}

export function voiceChoices(deps: VoiceChoicesDeps, group: GroupId, task?: string): ChoicesApi {
  const tasks = task ? [task] : (GROUP_TASKS[group] ?? []);
  return {
    async list(): Promise<ChoiceList> {
      const { models, ctx, overview } = await read(deps, tasks);
      // one task has a model in use; the whole group (the Models page) shows none as in use
      const chosen = task
        ? (defaultOf(models, task, deps.memory.get(choiceKey(task)))?.id ?? null)
        : null;
      return {
        choices: models.map((m) => voiceRow(m, tasks, ctx, chosen)),
        diskFreeBytes: overview?.disk_free_bytes ?? null,
        memoryBytes: overview?.memory_bytes ?? null,
      };
    },

    async choose(id) {
      const { models } = await read(deps, tasks);
      const m = models.find((x) => x.id === id);
      for (const t of tasks)
        if (!m || m.tasks.includes(t as never)) deps.memory.set(choiceKey(t), id);
    },

    async remove(id) {
      await deps.models.remove(id);
    },

    async get(id, on, signal) {
      const { models, ctx } = await read(deps, tasks);
      const m = models.find((x) => x.id === id);
      if (!m) throw new Error("That model is not in the list any more.");
      const steps: Step[] = [];
      if (m.state !== "ready" && !m.runtime_ready) {
        if (m.engine === "comfyui") {
          if (!ctx.image.installed) steps.push(await deps.engines.imageStep());
        } else if (m.engine === "sidecar") {
          const eng = ctx.lipsync;
          if (eng && !eng.installed) {
            steps.push({
              label: "Setting up the lip sync engine",
              bytes: eng.plan.bytes,
              run: async (report, signal2) => {
                await deps.voice.installLipsyncEngine(eng.plan.bytes);
                await pollInstall(() => deps.voice.lipsyncEngine(), report, signal2);
              },
            });
          }
        } else if (ctx.runtime && !ctx.runtime.installed) {
          const rt = ctx.runtime;
          steps.push({
            label: "Setting up the speech engine",
            bytes: rt.plan.bytes,
            run: async (report, signal2) => {
              await deps.voice.installRuntime(rt.plan.bytes);
              await pollInstall(() => deps.voice.runtime(), report, signal2);
            },
          });
        }
      }
      const entry = ctx.entries.get(id);
      if (entry && entry.bytes_missing > 0) {
        steps.push(modelStep(deps.models, entry, { acceptMemory: entry.fit?.verdict === "tight" }));
      }
      await runSteps(steps, on, signal);
      await this.choose(id);
    },
  };
}
