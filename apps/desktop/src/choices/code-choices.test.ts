// The picker's rows for Code: every model the engine lists, the one a new session starts with, and why not.
import type { CodeApi, CodeModel } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import { CODE_MODEL_KEY, chosenOf, codeChoices } from "./code-choices";

const model = (over: Partial<CodeModel>): CodeModel => ({
  id: "claude-sonnet-5-5",
  title: "Claude Sonnet 5.5",
  where: "cloud",
  default: false,
  ready: true,
  provider: "anthropic",
  provider_title: "Anthropic",
  tested: true,
  price: "$2 in / $10 out per million tokens",
  counted_in: "usd",
  ...over,
});

const MODELS = [
  model({ default: true }),
  model({ id: "anthropic:claude-opus-5-5", title: "Claude Opus 5.5", tested: false }),
  model({
    id: "openai:gpt-6",
    title: "GPT-6",
    provider: "openai",
    provider_title: "OpenAI",
    tested: false,
    price: "",
    counted_in: "tokens",
  }),
  model({ id: "gemini:gemini-3.8-pro", title: "Gemini 3.8 Pro", ready: false, tested: false }),
  model({ id: "qwen-27b-ollama", title: "Qwen 27B", where: "this-computer", provider: "ollama" }),
];

function made(installed = true, models: CodeModel[] = MODELS) {
  const kept = new Map<string, string>();
  const memory = {
    get: (k: string) => kept.get(k) ?? null,
    set: (k: string, v: string) => void kept.set(k, v),
  };
  const code = {
    engine: async () => ({ supported: true, installed, running: false }),
    models: async () => models,
  } as unknown as CodeApi;
  return { api: codeChoices({ code, memory }), kept };
}

describe("the models of Code in the picker", () => {
  it("lists every model: the key's under Cloud by provider, the tested first, the local on this computer", async () => {
    const { api } = made();
    const rows = (await api.list()).choices;
    expect(rows.map((r) => r.id)).toEqual(MODELS.map((m) => m.id));
    const opus = rows[1];
    expect(opus).toMatchObject({
      place: "cloud",
      providerTitle: "Anthropic",
      state: "ready",
      tier: "also",
    });
    expect(opus?.plain).toMatch(/^Not tested for coding here\./);
    expect(rows[0]).toMatchObject({ chosen: true, tier: "recommended" });
    expect(rows[0]?.plain).toMatch(/^Tested for coding\./);
    // no known price: said, and counted in tokens
    expect(rows[2]).toMatchObject({ price: "counted in tokens", providerTitle: "OpenAI" });
    // a model whose key is not saved says so and cannot be chosen
    expect(rows[3]).toMatchObject({ state: "unavailable" });
    expect(rows[3]?.unavailableReason).toMatch(/No key is saved/);
    expect(rows[4]?.place).toBeUndefined();
    expect(api.cloud?.product).toBe("Chat and writing");
  });

  it("remembers the model chosen for a new session", async () => {
    const { api, kept } = made();
    await api.choose("anthropic:claude-opus-5-5");
    expect(kept.get(CODE_MODEL_KEY)).toBe("anthropic:claude-opus-5-5");
    const rows = (await api.list()).choices;
    expect(rows.filter((r) => r.chosen).map((r) => r.id)).toEqual(["anthropic:claude-opus-5-5"]);
  });

  it("falls back to the first choice when the remembered model is gone or not ready", () => {
    expect(chosenOf(MODELS, "gemini:gemini-3.8-pro")?.id).toBe("claude-sonnet-5-5");
    expect(chosenOf(MODELS, "no-such")?.id).toBe("claude-sonnet-5-5");
    expect(chosenOf([model({ ready: false })], null)).toBeNull();
  });

  it("says the coding engine is needed on every row when it is not set up", async () => {
    const { api } = made(false);
    const rows = (await api.list()).choices;
    expect(rows.every((r) => r.state === "unavailable")).toBe(true);
    expect(rows[0]?.unavailableReason).toMatch(/Needs the coding engine/);
  });
});
