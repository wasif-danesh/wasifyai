// SPDX-License-Identifier: AGPL-3.0-only
// The picker's rows for groups made of the app's own catalogue models: images, video and the notebooks' search
// model (ADR-0086). Images and video run on the image engine, which a model's dialog sets up first.
import type { OwnKeysApi } from "@wasifyai/client";
import type { ChoiceList, ChoicesApi, ModelChoice } from "@wasifyai/ui";
import type { DiscoveryApi, FoundModel } from "../discovery";
import type { ModelEntry, ModelsApi } from "../models";
import { COPY, hostOf, plainFor } from "./copy";
import { keyedRow, leaveKey, withKeyed } from "./keyed";
import { modelStep, runSteps } from "./steps";
import type { Engines, Memory } from "./types";

export type CatalogueDeps = {
  models: ModelsApi;
  engines: Engines;
  memory: Memory;
  /** Settings › Your keys (ADR-0095, K3): images and video may run with the person's key */
  keys?: OwnKeysApi;
  /** what other tools left on the computer (ADR-0063): a model whose files are there is used, not downloaded */
  discovery?: Pick<DiscoveryApi, "state" | "use">;
};

const baseName = (path: string) => path.split(/[\\/]/).pop() ?? path;

/**
 * The found files that hold every file an entry still lacks, one per missing file, when another tool has all of them
 * in a folder the app can add (ComfyUI's models folder, for instance); null when anything is still to download.
 */
export function foundFor(e: ModelEntry, items: FoundModel[]): FoundModel[] | null {
  const missing = e.files.filter((f) => !f.present);
  if (missing.length === 0) return null;
  const usable = items.filter(
    (i) => i.use === "folder" && i.state === "can_use" && i.use_root !== null,
  );
  const picks: FoundModel[] = [];
  for (const f of missing) {
    const hit = usable.find((i) => baseName(i.path) === f.name);
    if (!hit) return null;
    picks.push(hit);
  }
  return picks;
}

/** The found files to use, one for each folder: using one adds its whole folder (ADR-0063). */
export function foldersOf(found: FoundModel[]): FoundModel[] {
  const seen = new Set<string>();
  return found.filter((i) => {
    const root = i.use_root ?? i.id;
    if (seen.has(root)) return false;
    seen.add(root);
    return true;
  });
}

export type CatalogueGroup = {
  /** which catalogue entries belong to the group */
  has: (e: ModelEntry) => boolean;
  /** runs on the image engine */
  imageEngine: boolean;
  /** the product of Settings › Your keys this group follows, if it can run on a key */
  keyed?: string;
  key: string;
};

export const CATALOGUE_GROUPS = {
  images: {
    has: (e) => e.product_id === "wasifyai-image",
    imageEngine: true,
    key: "images",
    keyed: "images",
  },
  video: {
    has: (e) => e.product_id === "wasifyai-video",
    imageEngine: true,
    key: "video",
    keyed: "video",
  },
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
  found: FoundModel[] | null = null,
): ModelChoice {
  const engineMissing = engine !== null && !engine.installed;
  const ready = e.status === "ready" && !engineMissing;
  const state: ModelChoice["state"] = ready
    ? "ready"
    : e.status !== "ready" && e.fit?.verdict === "too_big"
      ? "too_big"
      : "needs_download";
  const foundIn = state === "needs_download" && found ? (found[0]?.tool_title ?? null) : null;
  if (foundIn) {
    return {
      ...catalogueRow(e, engine, chosenId),
      foundIn,
      downloadBytes: 0,
      sizeBytes: e.bytes_total,
    };
  }
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
    source: "app",
    from: hostOf(e.source),
    sizeBytes: e.status === "ready" ? e.bytes_total : 0,
    removable: removable(e),
  };
}

export function catalogueChoices(deps: CatalogueDeps, group: CatalogueGroup): ChoicesApi {
  const key = `wasifyai:model:${group.key}`;
  const read = async () => {
    const [overview, engine, found] = await Promise.all([
      deps.models.overview(),
      group.imageEngine ? deps.engines.image().catch(() => null) : Promise.resolve(null),
      // a failed or switched-off scan only means nothing is offered from other tools
      deps.discovery
        ? deps.discovery
            .state()
            .then((s) => s.items)
            .catch(() => [])
        : Promise.resolve([]),
    ]);
    return { overview, engine, found, entries: overview.models.filter(group.has) };
  };
  return {
    async list(): Promise<ChoiceList> {
      const [{ overview, engine, found, entries }, keys] = await Promise.all([
        read(),
        group.keyed && deps.keys ? deps.keys.list().catch(() => null) : Promise.resolve(null),
      ]);
      const last = deps.memory.get(key);
      const chosen =
        entries.find((e) => e.id === last && e.status === "ready") ??
        entries.find((e) => e.status === "ready") ??
        null;
      return {
        choices: withKeyed(
          entries.map((e) => catalogueRow(e, engine, chosen?.id ?? null, foundFor(e, found))),
          group.keyed ? keyedRow(keys, group.keyed) : null,
        ),
        diskFreeBytes: overview.disk_free_bytes,
        memoryBytes: overview.memory_bytes,
      };
    },

    async choose(id) {
      if (group.keyed && (await leaveKey(deps.keys, group.keyed, id))) return;
      deps.memory.set(key, id);
    },

    async remove(id) {
      await deps.models.remove(id);
    },

    async get(id, on, signal) {
      const { engine, found, entries } = await read();
      let entry = entries.find((e) => e.id === id);
      if (!entry) throw new Error("That model is not in the list any more.");
      // files another tool already has: add their folders, then fetch only what is still missing
      const here = deps.discovery ? foundFor(entry, found) : null;
      if (here && deps.discovery) {
        on({
          label: `Using the files found in ${here[0]?.tool_title ?? "another tool"}`,
          fraction: null,
        });
        for (const f of foldersOf(here)) await deps.discovery.use(f.id);
        entry = (await read()).entries.find((e) => e.id === id) ?? entry;
      }
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
