// SPDX-License-Identifier: AGPL-3.0-only
// The picker's rows for groups made of the app's own catalogue models: images, video and the notebooks' search
// model (ADR-0086). Images and video run on the image engine, which a model's dialog sets up first.
import type { ChoiceList, ChoicesApi, ModelChoice } from "@wasifyai/ui";
import type { ModelEntry, ModelsApi } from "../models";
import { COPY, hostOf, plainFor } from "./copy";
import { modelStep, runSteps } from "./steps";
import type { Engines, Memory } from "./types";

export type CatalogueDeps = { models: ModelsApi; engines: Engines; memory: Memory };

export type CatalogueGroup = {
  /** which catalogue entries belong to the group */
  has: (e: ModelEntry) => boolean;
  /** runs on the image engine */
  imageEngine: boolean;
  key: string;
};

export const CATALOGUE_GROUPS = {
  images: { has: (e) => e.product_id === "wasifyai-image", imageEngine: true, key: "images" },
  video: { has: (e) => e.product_id === "wasifyai-video", imageEngine: true, key: "video" },
  documents: {
    has: (e) => e.id === "bge-small-en-v1.5",
    imageEngine: false,
    key: "documents",
  },
} satisfies Record<string, CatalogueGroup>;

/** The app can take a model off the computer when it keeps its files in its own folder. */
export const removable = (e: ModelEntry) => e.files.some((f) => f.present && f.removable);

export function catalogueRow(
  e: ModelEntry,
  engine: { installed: boolean; bytes: number; name: string } | null,
  chosenId: string | null,
): ModelChoice {
  const engineMissing = engine !== null && !engine.installed;
  const ready = e.status === "ready" && !engineMissing;
  const state: ModelChoice["state"] = ready
    ? "ready"
    : e.status !== "ready" && e.fit?.verdict === "too_big"
      ? "too_big"
      : "needs_download";
  return {
    id: e.id,
    title: e.title,
    plain: plainFor(e.id, e.title, e.note || undefined),
    tier: COPY[e.id]?.tier ?? "recommended",
    state,
    chosen: e.id === chosenId,
    downloadBytes: e.bytes_missing,
    engineBytes: engineMissing ? engine.bytes : 0,
    engineName: engineMissing ? engine.name : null,
    fit: e.fit?.verdict ?? null,
    fitReason: e.fit?.reason ?? null,
    licence: e.licence,
    commercial: e.voice?.commercial_use === "no" ? "no" : "yes",
    licenceUrl: null,
    source: "app",
    from: hostOf(e.source),
    sizeBytes: e.status === "ready" ? e.bytes_total : 0,
    removable: removable(e),
  };
}

export function catalogueChoices(deps: CatalogueDeps, group: CatalogueGroup): ChoicesApi {
  const key = `wasifyai:model:${group.key}`;
  const read = async () => {
    const overview = await deps.models.overview();
    const engine = group.imageEngine ? await deps.engines.image().catch(() => null) : null;
    return { overview, engine, entries: overview.models.filter(group.has) };
  };
  return {
    async list(): Promise<ChoiceList> {
      const { overview, engine, entries } = await read();
      const last = deps.memory.get(key);
      const chosen =
        entries.find((e) => e.id === last && e.status === "ready") ??
        entries.find((e) => e.status === "ready") ??
        null;
      return {
        choices: entries.map((e) => catalogueRow(e, engine, chosen?.id ?? null)),
        diskFreeBytes: overview.disk_free_bytes,
        memoryBytes: overview.memory_bytes,
      };
    },

    async choose(id) {
      deps.memory.set(key, id);
    },

    async remove(id) {
      await deps.models.remove(id);
    },

    async get(id, on, signal) {
      const { engine, entries } = await read();
      const entry = entries.find((e) => e.id === id);
      if (!entry) throw new Error("That model is not in the list any more.");
      const steps = [];
      if (engine && !engine.installed) steps.push(await deps.engines.imageStep());
      if (entry.bytes_missing > 0) {
        steps.push(modelStep(deps.models, entry, { acceptMemory: entry.fit?.verdict === "tight" }));
      }
      await runSteps(steps, on, signal);
      deps.memory.set(key, id);
    },
  };
}
