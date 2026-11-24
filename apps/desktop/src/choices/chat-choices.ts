// SPDX-License-Identifier: AGPL-3.0-only
// The chat group's rows and work (ADR-0086): models already on this computer (the app's own downloads, files other
// tools left, servers that are running) and a short list of ones worth getting from Hugging Face. A download
// through here is the person's consent to contact huggingface.co, which the dialog says.
import type { ChatPlanApi, CodeApi, CodeHarness, OwnKeysApi } from "@wasifyai/client";
import type { ChoiceList, ChoicesApi, ModelChoice, Tier } from "@wasifyai/ui";
import type { DiscoveryApi, FoundModel } from "../discovery";
import type { HubApi, Variant } from "../hub";
import type { LanguageApi, LanguageState } from "../language";
import { type ModelsApi, downloadFraction } from "../models";
import { type Parts, agentsApi, programOf } from "./agents";
import { CHAT_SHELF, type ChatShelfItem, recommendedChat } from "./copy";
import { chooseCloud, cloudOf, cloudRows, withCloud } from "./keyed";
import { type Step, pause, runSteps } from "./steps";
import type { Engines } from "./types";

export type ChatDeps = {
  language: LanguageApi;
  hub: HubApi;
  discovery: DiscoveryApi;
  models: ModelsApi;
  engines: Engines;
  /** Settings › Your keys (ADR-0095): while Chat and writing runs with the person's key, that is the chosen row */
  keys?: OwnKeysApi;
  /** the person's own Claude or ChatGPT plan (ADR-0110): the programs Code sets up and signs in, and the chat's choice */
  plan?: { plan: ChatPlanApi; code: CodeApi; parts: Parts };
};

/** The main chat's task: its model button also lists the person's own plan (ADR-0110). */
export const ASSISTANT_TASK = "assistant";

const PLAN = "plan:";
/** A plan row's picker id: `plan:<program>:<model>` ("" is the program's own choice). */
export const planId = (harness: string, model: string) => `${PLAN}${harness}:${model}`;
export function parsePlan(id: string): { harness: string; model: string } | null {
  if (!id.startsWith(PLAN)) return null;
  const [harness, ...rest] = id.slice(PLAN.length).split(":");
  return harness ? { harness, model: rest.join(":") } : null;
}

/** The Your plan tab's lines (ADR-0110). */
export const PLAN_WORDS = {
  intro:
    "The chat can answer on the Claude or ChatGPT plan you already pay for, with no key, through Claude Code or Codex on this computer.",
  foot: "The program answers on your plan; Wasify AI's actions still ask you on their cards. Pictures you attach are not sent to it.",
};

/** Where what the person writes goes, on each plan. */
const GOES_TO: Record<string, string> = { "claude-code": "Anthropic", codex: "OpenAI" };

/** A signed-in program's models as the chat's rows under Your plan, its own choice first. */
export function planRows(
  h: CodeHarness,
  models: { id: string; name: string }[],
  chosen: { harness: string; model: string } | null,
): ModelChoice[] {
  const p = programOf(h);
  const goes = GOES_TO[h.id] ?? h.title;
  return models.map((m, n) => ({
    id: planId(h.id, m.id),
    title: m.id ? m.name : "Its own choice",
    plain: `${m.id ? "" : `Whatever ${h.title} picks. `}The chat answers through ${h.title} on ${h.plan_words}, so what you write goes to ${goes}. Pictures you attach are not sent. Other writing tools keep their model.`,
    tier: n === 0 ? "recommended" : "also",
    state: "ready",
    chosen: chosen?.harness === h.id && chosen.model === m.id,
    downloadBytes: 0,
    engineBytes: 0,
    engineName: null,
    fit: null,
    fitReason: null,
    source: "server",
    unavailableReason: null,
    place: "agent",
    provider: h.id,
    providerTitle: h.title,
    price: p.payer,
    works: true,
  }));
}

/** The chat's plan rows (none when the programs cannot be read), and the plan in use. */
async function planOf(deps: ChatDeps["plan"]) {
  if (!deps) return { rows: [] as ModelChoice[], inUse: false };
  const [plan, listed] = await Promise.all([
    deps.plan.get().catch(() => null),
    deps.code.harnesses().catch(() => [] as CodeHarness[]),
  ]);
  if (!plan) return { rows: [], inUse: false };
  const rows = listed
    .filter((h) => h.installed && h.signed_in)
    .flatMap((h) =>
      planRows(h, plan.programs.find((p) => p.id === h.id)?.models ?? [], plan.choice),
    );
  return { rows, inUse: rows.some((r) => r.chosen) };
}

const EMBEDDING = /embed|bge-|minilm|e5-|gte-|arctic-embed/i;
const HUB = "hub:";
const SERVER = "server:";

/** The folder the app puts a hub download in, by the engine's rule (desktop_hub.build_download). */
export const folderOf = (repo: string) => `language/${repo.replace("/", "--")}`;

const isFrom = (f: FoundModel, repo: string) => f.path.replace(/\\/g, "/").includes(folderOf(repo));

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
      source: "app",
      from: "huggingface.co",
    });
  }
  return out;
}

/** The variant to fetch: the list's file (the usual 4-bit one), else the one nearest the size the list promised. */
export function pickVariant(
  variants: Variant[],
  promised: number,
  quant = "Q4_K_M",
): Variant | null {
  const usual = variants.find((v) => v.quant.toUpperCase() === quant.toUpperCase());
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
      "The model was downloaded but could not be found. Look in the Model hub, under Advanced.",
    );
  }

  return {
    cloud: cloudOf(["chat"]),
    ...(deps.plan
      ? {
          agents: agentsApi({ code: deps.plan.code, parts: deps.plan.parts }),
          agentsTab: "Your plan",
          agentsWords: PLAN_WORDS,
        }
      : {}),
    async list(): Promise<ChoiceList> {
      const [{ state, overview, engine, shelf }, cloud, plan] = await Promise.all([
        read(),
        cloudRows(deps.keys, "chat"),
        planOf(deps.plan),
      ]);
      const local = rows(state, shelf, engine, overview?.memory_bytes ?? null);
      const models = withCloud(local, cloud);
      return {
        // while chat runs on a cloud model, no model on this computer is the one in use; on a plan, neither is
        choices: [
          ...(plan.inUse ? models.map((c) => ({ ...c, chosen: false })) : models),
          ...plan.rows,
        ],
        diskFreeBytes: overview?.disk_free_bytes ?? null,
        memoryBytes: overview?.memory_bytes ?? null,
      };
    },

    async remove(id) {
      await deps.hub.remove(id);
    },

    async choose(id) {
      // a plan makes the chat answer through its program; any other model takes the chat off the plan
      const plan = parsePlan(id);
      if (plan && deps.plan) {
        await deps.plan.plan.use(plan);
        return;
      }
      if (deps.plan && (await deps.plan.plan.get().catch(() => null))?.choice)
        await deps.plan.plan.use(null);
      // a cloud model makes chat run there; one on this computer takes chat off the cloud (the keys stay)
      if (await chooseCloud(deps.keys, "chat", id)) return;
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
              const variant = pickVariant(detail.variants, item.bytes, item.quant);
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
