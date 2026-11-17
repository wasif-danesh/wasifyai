// SPDX-License-Identifier: AGPL-3.0-only
// The models a coding session can run on (ADR-0101, decision 7), as the picker's rows: the ones run through the
// coding evaluation, the model on this computer, and every other chat model a key saved under Settings › Your keys
// lists (owner, 2026-11-15). The choice is the model a NEW session starts with; a session keeps the model it began
// with. It is remembered in this window, since nothing in the engine runs on it until a session starts.
// The person's own agent programs (ADR-0107, stage H2) are under Your agent: for each one that is signed in, the
// models its plan offers, as the program names them, with "Its own choice" first.
import type { CodeApi, CodeHarness, CodeModel } from "@wasifyai/client";
import type { ChoiceList, ChoicesApi, ModelChoice } from "@wasifyai/ui";
import { type Parts, agentsApi, programOf } from "./agents";
import { cloudOf } from "./keyed";
import type { Memory } from "./types";

export const CODE_MODEL_KEY = "wasifyai.code.model";
const NEEDS_ENGINE = "Needs the coding engine: set it up in Settings, under Optional parts";

/** The model a new session starts with: the one chosen last if it is still ready, else the first choice, else any. */
export function chosenOf(models: CodeModel[], last: string | null): CodeModel | null {
  const ready = models.filter((m) => m.ready);
  return ready.find((m) => m.id === last) ?? ready.find((m) => m.default) ?? ready[0] ?? null;
}

function plainOf(m: CodeModel): string {
  const tested = m.tested === false ? "Not tested for coding here." : "Tested for coding.";
  if (m.where !== "cloud")
    return `${tested} Runs on this computer: nothing is paid and nothing leaves it.`;
  const counted =
    m.counted_in === "tokens"
      ? " Its price is not known here, so a session is counted and limited in tokens."
      : "";
  return `${tested} The parts of files the agent reads are sent to ${m.provider_title || "its provider"}, with your key.${counted}`;
}

export function codeRow(m: CodeModel, chosen: boolean, engineReady: boolean): ModelChoice {
  const cloud = m.where === "cloud";
  const reason = !engineReady
    ? NEEDS_ENGINE
    : m.ready
      ? null
      : cloud
        ? "No key is saved for it: save one in Settings, under Cloud keys"
        : "Its address is not set";
  return {
    id: m.id,
    title: m.title,
    plain: plainOf(m),
    tier: m.tested === false ? "also" : "recommended",
    state: reason ? "unavailable" : "ready",
    chosen,
    downloadBytes: 0,
    engineBytes: 0,
    engineName: null,
    fit: null,
    fitReason: null,
    source: cloud ? "server" : "app",
    unavailableReason: reason,
    ...(cloud
      ? {
          place: "cloud" as const,
          provider: m.provider ?? "",
          providerTitle: m.provider_title || "Your key",
          price: m.price || (m.counted_in === "tokens" ? "counted in tokens" : ""),
          works: true,
        }
      : {}),
  };
}

/** The id of a program's own choice of model: the session's `model` when the program picks. */
export const agentDefault = (harness: string) => `${harness}:default`;

type Listed = { id: string; name: string; program_model: string; tested?: string };

/** A signed-in program's model in words: whether the coding evaluation measured it, and what pays. */
function agentPlain(title: string, tested: string | undefined): string {
  const said = tested ? `Tested for coding here: ${tested}.` : "Not tested for coding here.";
  return `${said} ${title} runs it on your plan.`;
}

/** A signed-in program's models as rows, "Its own choice" first. */
export function agentRows(h: CodeHarness, listed: Listed[], last: string | null): ModelChoice[] {
  const p = programOf(h);
  const own = listed.filter((m) => m.program_model !== "default");
  const all = [
    {
      id: agentDefault(h.id),
      name: "Its own choice",
      plain: `Whatever ${h.title} picks on your plan.`,
    },
    ...own.map((m) => ({ id: m.id, name: m.name, plain: agentPlain(h.title, m.tested) })),
  ];
  return all.map((m, n) => ({
    id: m.id,
    title: m.name,
    plain: m.plain,
    tier: n === 0 ? "recommended" : "also",
    state: "ready",
    chosen: m.id === last,
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

export function codeChoices(deps: { code: CodeApi; memory: Memory; parts?: Parts }): ChoicesApi {
  // what each program's plan offers, read once per sign-in: listing them starts the program
  const offered = new Map<string, Promise<Listed[]>>();
  const modelsOf = (h: CodeHarness) => {
    const key = `${h.id}|${h.plan}|${h.how}`;
    if (!offered.has(key)) {
      const asked = deps.code
        .harnessModels(h.id)
        .then((found) => found.models)
        .catch(() => {
          offered.delete(key); // asked again next time
          return [];
        });
      offered.set(key, asked);
    }
    return offered.get(key) as Promise<Listed[]>;
  };
  return {
    cloud: cloudOf(["chat"]),
    ...(deps.parts ? { agents: agentsApi({ code: deps.code, parts: deps.parts }) } : {}),
    async list(): Promise<ChoiceList> {
      const engine = await deps.code.engine();
      // the models are the engine's to say; where the coding engine is not set up they are still listed
      const models = await deps.code.models().catch(() => [] as CodeModel[]);
      const engineReady = engine.supported && engine.installed;
      const last = deps.memory.get(CODE_MODEL_KEY);
      const signed =
        deps.parts && engineReady
          ? (await deps.code.harnesses().catch(() => [] as CodeHarness[])).filter(
              (h) => h.installed && h.signed_in,
            )
          : [];
      const agents = (
        await Promise.all(signed.map(async (h) => agentRows(h, await modelsOf(h), last)))
      ).flat();
      // a program's model chosen last is the one in use while its program is signed in
      const onAgent = agents.some((a) => a.chosen);
      const chosen = onAgent ? null : chosenOf(models, last);
      return {
        choices: [...models.map((m) => codeRow(m, m.id === chosen?.id, engineReady)), ...agents],
        diskFreeBytes: null,
        memoryBytes: null,
      };
    },
    async choose(id) {
      deps.memory.set(CODE_MODEL_KEY, id);
    },
    async get(id) {
      deps.memory.set(CODE_MODEL_KEY, id);
    },
  };
}
