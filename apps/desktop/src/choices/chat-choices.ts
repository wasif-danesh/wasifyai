// SPDX-License-Identifier: AGPL-3.0-only
// The chat group's rows and work (ADR-0086): models already on this computer (the app's own downloads, files other
// tools left, servers that are running) and a short list of ones worth getting from Hugging Face. A download
// through here is the person's consent to contact huggingface.co, which the dialog says.
import type { ChoiceList, ChoicesApi, ModelChoice, Tier } from "@wasifyai/ui";
import type { DiscoveryApi, FoundModel } from "../discovery";
import type { HubApi, Variant } from "../hub";
import type { LanguageApi, LanguageState } from "../language";
import { type ModelsApi, downloadFraction } from "../models";
import { CHAT_SHELF, type ChatShelfItem, recommendedChat } from "./copy";
import { type Step, pause, runSteps } from "./steps";
import type { Engines } from "./types";

export type ChatDeps = {
  language: LanguageApi;
  hub: HubApi;
  discovery: DiscoveryApi;
  models: ModelsApi;
  engines: Engines;
};

const EMBEDDING = /embed|bge-|minilm|e5-|gte-|arctic-embed/i;
const HUB = "hub:";
const SERVER = "server:";

/** The folder the app puts a hub download in, by the engine's rule (desktop_hub.build_download). */
export const folderOf = (repo: string) => `language/${repo.replace("/", "--")}`;

const isFrom = (f: FoundModel, repo: string) => f.path.replace(/\\/g, "/").includes(folderOf(repo));

export function commercialOf(licence: string): ModelChoice["commercial"] {
  if (/apache|mit\b|bsd/i.test(licence)) return "yes";
  if (/llama|gemma|openrail|community/i.test(licence)) return "conditional";
  return "unreviewed";
}

/** How a model of `needGb` of memory sits on a computer with `memoryBytes`: a guess; the engine decides on download. */
export function fitOf(needGb: number, memoryBytes: number | null): ModelChoice["fit"] {
  if (memoryBytes === null) return null;
  const need = needGb * 1e9;
  if (memoryBytes < need) return "too_big";
  return memoryBytes < need * 1.5 ? "tight" : "fits";
}

export function serverId(s: { tool: string; url: string; model: string }) {
  return `${SERVER}${s.tool}|${s.url}|${s.model}`;
}

function rows(
  state: LanguageState,
  shelf: ChatShelfItem[],
  engine: { installed: boolean; bytes: number; name: string },
  memoryBytes: number | null,
): ModelChoice[] {
  const recommended = recommendedChat(memoryBytes);
  const out: ModelChoice[] = [];
  const engineMissing = !engine.installed;
  const engineFields = {
    engineBytes: engineMissing ? engine.bytes : 0,
    engineName: engineMissing ? engine.name : null,
  };

  for (const f of state.files) {
    if (f.kind !== "language" || f.state === "unsupported" || f.state === "later") continue;
    const item = shelf.find((s) => isFrom(f, s.repo));
    const tier: Tier = item
      ? item.repo === recommended
        ? "recommended"
        : (item.tier ?? "also")
      : "advanced";
    out.push({
      id: f.id,
      title: item?.title ?? f.name,
      plain: item?.plain ?? `Found in ${f.tool_title}${f.quant ? `, ${f.quant}` : ""}.`,
      tier,
      state: engineMissing ? "needs_download" : f.fit?.verdict === "too_big" ? "too_big" : "ready",
      chosen: f.chosen,
      downloadBytes: 0,
      ...engineFields,
      fit: f.fit?.verdict ?? null,
      fitReason: f.fit?.reason ?? null,
      licence: f.licence || "unknown",
      commercial: commercialOf(f.licence),
      licenceUrl: null,
      source: f.tool === "app" ? "app" : "found",
      sizeBytes: f.size,
      removable: f.tool === "app",
    });
  }

  for (const s of state.servers) {
    if (EMBEDDING.test(s.model)) continue; // a model for search, not for answering
    out.push({
      id: serverId(s),
      title: s.model,
      plain: `Running in ${s.title}. Answers come from that tool.`,
      tier: "advanced",
      state: "ready",
      chosen: s.chosen,
      downloadBytes: 0,
      engineBytes: 0,
      engineName: null,
      fit: null,
      fitReason: null,
      licence: "unknown",
      commercial: "unreviewed",
      licenceUrl: null,
      source: "server",
    });
  }

  for (const item of shelf) {
    if (state.files.some((f) => isFrom(f, item.repo))) continue;
    const fit = fitOf(item.memoryGb, memoryBytes);
    out.push({
      id: `${HUB}${item.repo}`,
      title: item.title,
      plain: item.plain,
      tier: item.repo === recommended ? "recommended" : (item.tier ?? "also"),
      state: fit === "too_big" ? "too_big" : "needs_download",
      chosen: false,
      downloadBytes: item.bytes,
      ...engineFields,
      fit,
      fitReason: fit === "too_big" ? `It needs about ${item.memoryGb} GB of memory.` : null,
      licence: item.licence,
      commercial: commercialOf(item.licence),
      licenceUrl: null,
      source: "app",
      from: "huggingface.co",
    });
  }
  return out;
}

/** The variant to fetch: the usual 4-bit file, else the one nearest the size the list promised. */
export function pickVariant(variants: Variant[], promised: number): Variant | null {
  const usual = variants.find((v) => /^Q4_K_M$/i.test(v.quant));
  if (usual) return usual;
  const sorted = [...variants].sort(
    (a, b) => Math.abs(a.size - promised) - Math.abs(b.size - promised),
  );
  return sorted[0] ?? null;
}

export function chatChoices(deps: ChatDeps): ChoicesApi {
  const read = async () => {
    const [state, hub, overview, engine] = await Promise.all([
      deps.language.state(),
      deps.hub.state().catch(() => null),
      deps.models.overview().catch(() => null),
      deps.engines.language().catch(() => ({
        installed: true,
        supported: true,
        bytes: 0,
        name: "The chat engine",
      })),
    ]);
    const known = new Set((hub?.shelf ?? []).map((s) => s.repo));
    const shelf = CHAT_SHELF.filter((s) => known.size === 0 || known.has(s.repo));
    return { state, overview, engine, shelf };
  };

  /** Rescan, then find the file a download left. */
  async function fileOf(repo: string, signal: AbortSignal) {
    await deps.discovery.scan().catch(() => {});
    for (let i = 0; i < 30; i++) {
      await pause(i === 0 ? 300 : 1000, signal);
      const found = (await deps.language.state()).files.find((f) => isFrom(f, repo));
      if (found) return found;
      if (signal.aborted) break;
    }
    throw new Error(
      "The model was downloaded but could not be found. Look in Models, under Advanced.",
    );
  }

  return {
    async list(): Promise<ChoiceList> {
      const { state, overview, engine, shelf } = await read();
      return {
        choices: rows(state, shelf, engine, overview?.memory_bytes ?? null),
        diskFreeBytes: overview?.disk_free_bytes ?? null,
        memoryBytes: overview?.memory_bytes ?? null,
      };
    },

    async remove(id) {
      await deps.hub.remove(id);
    },

    async choose(id) {
      const state = await deps.language.state();
      const context = state.selected?.context ?? 8192;
      if (id.startsWith(SERVER)) {
        const s = state.servers.find((x) => serverId(x) === id);
        if (!s) throw new Error("That server is not running any more.");
        await deps.language.choose({
          server: { tool: s.tool, url: s.url, model: s.model },
          context,
        });
      } else {
        await deps.language.choose({ item_id: id, context });
      }
    },

    async get(id, on, signal) {
      const { state, engine, shelf } = await read();
      const steps: Step[] = [];
      if (!engine.installed) steps.push(await deps.engines.languageStep());
      let chosenId = id;

      if (id.startsWith(HUB)) {
        const repo = id.slice(HUB.length);
        const item = shelf.find((s) => s.repo === repo);
        if (!item) throw new Error("That model is not in the list any more.");
        const have = state.files.find((f) => isFrom(f, repo));
        // a download that finished before a later step failed is not fetched again
        if (have) chosenId = have.id;
        else
          steps.push({
            label: `Downloading ${item.title}`,
            bytes: item.bytes,
            async run(report, signal2) {
              // pressing "Download and use" is the consent to contact huggingface.co
              if (!(await deps.hub.state()).enabled) await deps.hub.setEnabled(true);
              const detail = await deps.hub.model(repo);
              const variant = pickVariant(detail.variants, item.bytes);
              if (!variant) throw new Error("No file of this model can be run here.");
              const started = await deps.hub.download(
                repo,
                variant,
                variant.fit?.verdict === "tight",
              );
              const stop = () => void deps.models.cancel(started.id).catch(() => {});
              signal2.addEventListener("abort", stop, { once: true });
              try {
                for (;;) {
                  const d = await deps.models.download(started.id);
                  report(downloadFraction(d));
                  if (d.status === "done") break;
                  if (d.status === "failed") throw new Error(d.error || "The download failed.");
                  if (d.status === "cancelled" || signal2.aborted) throw new Error("Stopped.");
                  await pause(1000, signal2);
                }
              } finally {
                signal2.removeEventListener("abort", stop);
              }
              chosenId = (await fileOf(repo, signal2)).id;
            },
          });
      } else if (!id.startsWith(SERVER) && !state.files.some((f) => f.id === id)) {
        throw new Error("That model is not in the list any more.");
      }

      await runSteps(steps, on, signal);
      await this.choose(chosenId);
    },
  };
}
