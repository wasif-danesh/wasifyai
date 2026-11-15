// SPDX-License-Identifier: AGPL-3.0-only
// The models a coding session can run on (ADR-0101, decision 7), as the picker's rows: the ones run through the
// coding evaluation, the model on this computer, and every other chat model a key saved under Settings › Your keys
// lists (owner, 2026-11-15). The choice is the model a NEW session starts with; a session keeps the model it began
// with. It is remembered in this window, since nothing in the engine runs on it until a session starts.
import type { CodeApi, CodeModel } from "@wasifyai/client";
import type { ChoiceList, ChoicesApi, ModelChoice } from "@wasifyai/ui";
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
        ? "No key is saved for it: save one in Settings, under Your keys"
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

export function codeChoices(deps: { code: CodeApi; memory: Memory }): ChoicesApi {
  return {
    cloud: cloudOf(["chat"]),
    async list(): Promise<ChoiceList> {
      const engine = await deps.code.engine();
      // the models are the engine's to say; where the coding engine is not set up they are still listed
      const models = await deps.code.models().catch(() => [] as CodeModel[]);
      const engineReady = engine.supported && engine.installed;
      const chosen = chosenOf(models, deps.memory.get(CODE_MODEL_KEY));
      return {
        choices: models.map((m) => codeRow(m, m.id === chosen?.id, engineReady)),
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
