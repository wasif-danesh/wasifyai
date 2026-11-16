// The picker's rows for Code: every model the engine lists, the one a new session starts with, and why not.
import type { CodeApi, CodeHarness, CodeModel, ComponentView } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { planName } from "./agents";
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

describe("the person's own agent programs under Your agent (ADR-0107)", () => {
  const CLAUDE: CodeHarness = {
    id: "claude-code",
    title: "Claude Code",
    plan_words: "your Claude plan",
    installed: true,
    signed_in: true,
    how: "plan",
    plan: "Max",
    signing_in: false,
    page: "",
  };
  const CODEX: CodeHarness = { ...CLAUDE, id: "codex", title: "Codex", signed_in: false };

  function withAgents(
    listed = vi.fn(async () => ({ models: SONNET_HAIKU, current: "", error: "" })),
  ) {
    const kept = new Map<string, string>();
    const memory = {
      get: (k: string) => kept.get(k) ?? null,
      set: (k: string, v: string) => void kept.set(k, v),
    };
    const code = {
      engine: async () => ({ supported: true, installed: true, running: false }),
      models: async () => MODELS,
      harnesses: async () => [CLAUDE, CODEX],
      harnessModels: listed,
    } as unknown as CodeApi;
    const parts = {
      get: async () =>
        ({
          id: "harness",
          title: "Agent programs",
          status: { state: "installed", version: "1", accelerator: "" },
          can: { stop: false, repair: true, remove: true },
        }) as ComponentView,
      install: vi.fn(async () => ({})),
      uninstall: vi.fn(async () => ({})),
    };
    return { api: codeChoices({ code, memory, parts }), kept, listed, parts };
  }
  const SONNET_HAIKU = [
    { id: "claude-code:default", name: "Default (recommended)", program_model: "default" },
    { id: "claude-code:sonnet", name: "Sonnet", program_model: "sonnet" },
    { id: "claude-code:haiku", name: "Haiku", program_model: "haiku" },
  ];

  it("lists a signed-in program's models, its own choice first, and none for one not signed in", async () => {
    const { api, listed } = withAgents();
    const rows = (await api.list()).choices.filter((r) => r.place === "agent");
    expect(rows.map((r) => [r.id, r.title, r.tier])).toEqual([
      ["claude-code:default", "Its own choice", "recommended"],
      ["claude-code:sonnet", "Sonnet", "also"],
      ["claude-code:haiku", "Haiku", "also"],
    ]);
    expect(rows[0]).toMatchObject({ providerTitle: "Claude Code", price: "Your Claude plan" });
    expect(listed).toHaveBeenCalledWith("claude-code");
    expect(listed).not.toHaveBeenCalledWith("codex");
    // asked once: listing them starts the program
    await api.list();
    expect(listed).toHaveBeenCalledTimes(1);
    expect(api.agents).toBeDefined();
  });

  it("says which of a program's models the coding evaluation measured", async () => {
    const { api, listed } = withAgents();
    listed.mockResolvedValueOnce({
      models: [{ ...SONNET_HAIKU[2], tested: "33 of 36 tasks passed" }, SONNET_HAIKU[1]],
      current: "default",
      error: "",
    } as never);
    const rows = (await api.list()).choices.filter((r) => r.place === "agent");
    const by = Object.fromEntries(rows.map((r) => [r.id, r.plain]));
    expect(by["claude-code:haiku"]).toBe(
      "Tested for coding here: 33 of 36 tasks passed. Claude Code runs it on your plan.",
    );
    expect(by["claude-code:sonnet"]).toMatch(/^Not tested for coding here\. /);
  });

  it("keeps a program's model chosen, and then no key model is in use", async () => {
    const { api } = withAgents();
    await api.choose("claude-code:sonnet");
    const rows = (await api.list()).choices;
    expect(rows.filter((r) => r.chosen).map((r) => r.id)).toEqual(["claude-code:sonnet"]);
  });

  it("names a plan only when it says more than who pays", () => {
    expect(planName({ ...CLAUDE, plan: "max" })).toBe("Max");
    expect(planName({ ...CODEX, plan: "ChatGPT", plan_words: "your ChatGPT plan" })).toBe("");
  });

  it("gives the tab the programs and the part's state, and sets the part up", async () => {
    const { api, parts } = withAgents();
    const now = await api.agents?.programs();
    expect(now?.setup).toMatchObject({ state: "installed" });
    expect(now?.programs.map((p) => [p.title, p.account, p.signedIn])).toEqual([
      ["Claude Code", "Claude", true],
      ["Codex", "ChatGPT", false],
    ]);
    await api.agents?.setUp(694_400_000);
    expect(parts.install).toHaveBeenCalledWith("harness", 694_400_000);
  });
});
