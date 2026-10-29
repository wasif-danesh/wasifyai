import type { OwnKeysApi, VoiceApi, VoiceModelInfo } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import type { DiscoveryApi, FoundModel } from "../discovery";
import type { HubApi } from "../hub";
import type { LanguageApi, LanguageState } from "../language";
import type { ModelEntry, ModelsApi } from "../models";
import { CATALOGUE_GROUPS, catalogueChoices } from "./catalogue-choices";
import { KEYED, chatChoices, fitOf, pickVariant } from "./chat-choices";
import { recommendedChat } from "./copy";
import type { Step } from "./steps";
import type { Engines, Memory } from "./types";
import { choiceKey, voiceChoices } from "./voice-choices";

const never = new AbortController().signal;
const noStep: Step = { label: "engine", bytes: 1, run: async () => {} };

function engines(image = true, language = true): Engines {
  return {
    image: async () => ({
      installed: image,
      supported: true,
      bytes: 2e9,
      name: "The image engine",
    }),
    language: async () => ({
      installed: language,
      supported: true,
      bytes: 3e8,
      name: "The chat engine",
    }),
    imageStep: async () => noStep,
    languageStep: async () => noStep,
  };
}

function memory(): Memory & { data: Record<string, string> } {
  const data: Record<string, string> = {};
  return {
    data,
    get: (k) => data[k] ?? null,
    set: (k, v) => {
      data[k] = v;
    },
  };
}

const entry = (over: Partial<ModelEntry> = {}): ModelEntry => ({
  id: "flux2-klein-4b",
  product_id: "wasifyai-image",
  title: "FLUX.2 klein 4B",
  source: "x",
  note: "",
  approx_ram_gb: 12,
  status: "missing",
  files: [],
  bytes_total: 10e9,
  bytes_missing: 10e9,
  memory_warning: null,
  fit: {
    verdict: "fits",
    reason: "",
    needed_bytes: 1,
    budget_bytes: 2,
    capacity_bytes: 2,
    estimate: false,
    partly_on_cpu: false,
  },
  ...over,
});

const overview = (models: ModelEntry[]) => ({
  models,
  folders: { models_dir: "/m", extra_dirs: [] },
  memory_bytes: 32e9,
  disk_free_bytes: 500e9,
  download: null,
});

describe("images and video", () => {
  const imageKey = (mode: "here" | "key") => {
    const save = vi.fn(async () => ({}));
    const keys = {
      list: async () => ({
        can_save: true,
        providers: [
          {
            id: "fal",
            title: "fal.ai",
            kind: "media",
            host: "fal.ai",
            needs_base: false,
            models: [],
          },
        ],
        products: ["images", "video"].map((id) => ({
          id,
          title: id,
          kind: "media",
          mode: id === "images" ? mode : "here",
          provider: id === "images" && mode === "key" ? "fal" : null,
          model: id === "images" && mode === "key" ? "fal-ai/flux-2" : null,
          base_url: null,
          key_saved: mode === "key",
          state: id === "images" && mode === "key" ? "ok" : "here",
          said: null,
          tested_at: null,
          models: [],
        })),
      }),
      save,
    } as unknown as OwnKeysApi;
    return { keys, save };
  };

  it("with images on the person's key, that row is in use even with no image engine here", async () => {
    const models = {
      overview: async () => overview([entry({ status: "missing", bytes_missing: 9e9 })]),
    } as unknown as ModelsApi;
    const deps = { models, engines: engines(false), memory: memory(), keys: imageKey("key").keys };
    const rows = (await catalogueChoices(deps, CATALOGUE_GROUPS.images).list()).choices;
    expect(rows[0]).toMatchObject({
      id: "key:images",
      chosen: true,
      state: "ready",
      title: "fal-ai/flux-2 · with your key · fal.ai",
    });
    expect(rows.filter((r) => r.chosen)).toHaveLength(1);
    // video follows its own setting, which is on this computer
    const video = (await catalogueChoices(deps, CATALOGUE_GROUPS.video).list()).choices;
    expect(video.some((r) => r.id.startsWith("key:"))).toBe(false);
  });

  it("choosing a model on this computer takes images off the key", async () => {
    const models = {
      overview: async () => overview([entry({ status: "ready", bytes_missing: 0 })]),
    } as unknown as ModelsApi;
    const { keys, save } = imageKey("key");
    const mem = memory();
    const api = catalogueChoices(
      { models, engines: engines(true), memory: mem, keys },
      CATALOGUE_GROUPS.images,
    );
    await api.choose("key:images");
    expect(save).not.toHaveBeenCalled();
    await api.choose(entry({}).id);
    expect(save).toHaveBeenCalledWith("images", "here");
  });

  it("shows a model that is on the computer as ready only when its engine is too", async () => {
    const models = {
      overview: async () => overview([entry({ status: "ready", bytes_missing: 0 })]),
    } as unknown as ModelsApi;
    const withEngine = await catalogueChoices(
      { models, engines: engines(true), memory: memory() },
      CATALOGUE_GROUPS.images,
    ).list();
    expect(withEngine.choices[0]).toMatchObject({ state: "ready", chosen: true, engineBytes: 0 });
    const without = await catalogueChoices(
      { models, engines: engines(false), memory: memory() },
      CATALOGUE_GROUPS.images,
    ).list();
    expect(without.choices[0]).toMatchObject({
      state: "needs_download",
      engineBytes: 2e9,
      engineName: "The image engine",
    });
  });

  it("gets the engine, then the files, then remembers the choice", async () => {
    const order: string[] = [];
    const e = engines(false);
    e.imageStep = async () => ({
      label: "engine",
      bytes: 2e9,
      run: async () => void order.push("engine"),
    });
    const models = {
      overview: async () => overview([entry()]),
      start: vi.fn(async () => {
        order.push("files");
        return {
          id: "d",
          entry_id: "x",
          files: [],
          bytes_total: 1,
          bytes_done: 1,
          status: "done",
          current: "",
          error: "",
        };
      }),
      download: async () => ({
        id: "d",
        entry_id: "x",
        files: [],
        bytes_total: 1,
        bytes_done: 1,
        status: "done",
        current: "",
        error: "",
      }),
      cancel: vi.fn(),
    } as unknown as ModelsApi;
    const mem = memory();
    await catalogueChoices({ models, engines: e, memory: mem }, CATALOGUE_GROUPS.images).get(
      "flux2-klein-4b",
      () => {},
      never,
    );
    expect(order).toEqual(["engine", "files"]);
    expect(mem.data["wasifyai:model:images"]).toBe("flux2-klein-4b");
  });

  it("does not offer a model that will not fit", async () => {
    const big = entry({
      fit: {
        verdict: "too_big",
        reason: "Needs 40 GB.",
        needed_bytes: 1,
        budget_bytes: 1,
        capacity_bytes: 1,
        estimate: false,
        partly_on_cpu: false,
      },
    });
    const models = { overview: async () => overview([big]) } as unknown as ModelsApi;
    const list = await catalogueChoices(
      { models, engines: engines(), memory: memory() },
      CATALOGUE_GROUPS.images,
    ).list();
    expect(list.choices[0]).toMatchObject({ state: "too_big", fitReason: "Needs 40 GB." });
  });
});

const voiceModel = (over: Partial<VoiceModelInfo> = {}): VoiceModelInfo =>
  ({
    id: "parakeet-tdt-0.6b-v3",
    title: "Parakeet",
    engine: "onnx",
    family: "x",
    tasks: ["transcribe"],
    recommended: ["transcribe"],
    languages: [],
    sample_rate: 16000,
    measured: { platform: "", speed_x: null, memory_gb: null, load_s: null },
    voices: [],
    default_voice: null,
    options: [],
    music: {},
    state: "can_install",
    files_ready: false,
    runtime_ready: false,
    bytes_missing: 9e8,
    ...over,
  }) as VoiceModelInfo;

describe("speech and listening", () => {
  const voice = (models: VoiceModelInfo[], installed = false) =>
    ({
      models: async () => models,
      runtime: async () => ({ installed, plan: { bytes: 4e8 } }),
      lipsyncEngine: async () => ({ installed: true, plan: { bytes: 0 } }),
    }) as unknown as VoiceApi;
  const models = { overview: async () => overview([]) } as unknown as ModelsApi;

  it("adds the speech engine to what a missing model costs", async () => {
    const api = voiceChoices(
      { voice: voice([voiceModel()]), models, memory: memory(), engines: engines() },
      "listening",
      "transcribe",
    );
    const [row] = (await api.list()).choices;
    expect(row).toMatchObject({
      state: "needs_download",
      downloadBytes: 9e8,
      engineBytes: 4e8,
      engineName: "The speech engine",
    });
  });

  it("uses the model the person chose last time", async () => {
    const ready = [
      voiceModel({ id: "a", state: "ready", recommended: [] }),
      voiceModel({ id: "b", state: "ready", recommended: ["transcribe"] }),
    ];
    const mem = memory();
    mem.set(choiceKey("transcribe"), "a");
    const api = voiceChoices(
      { voice: voice(ready), models, memory: mem, engines: engines() },
      "listening",
      "transcribe",
    );
    const rows = (await api.list()).choices;
    expect(rows.find((r) => r.chosen)?.id).toBe("a");
    await api.choose("b");
    expect(mem.get(choiceKey("transcribe"))).toBe("b");
  });

  it("a whole group lists each model once and marks none in use", async () => {
    const m = voiceModel({
      id: "k",
      tasks: ["speak", "clone"],
      recommended: ["speak"],
      state: "ready",
    });
    const api = voiceChoices(
      { voice: voice([m]), models, memory: memory(), engines: engines() },
      "voice",
    );
    const list = await api.list();
    expect(list.choices).toHaveLength(1);
    expect(list.choices[0]?.chosen).toBe(false);
  });
});

const found = (over: Partial<FoundModel> = {}): FoundModel => ({
  id: "f1",
  name: "Qwen3-4B-Q4_K_M.gguf",
  kind: "language",
  family: "qwen3",
  format: "gguf",
  quant: "Q4_K_M",
  size: 2.5e9,
  path: "/data/models/language/unsloth--Qwen3-4B-GGUF/Qwen3-4B-Q4_K_M.gguf",
  tool: "app",
  tool_title: "Wasify AI",
  state: "can_use",
  reason: "",
  use_root: null,
  use: "chat",
  needs_gb: 4,
  fit: null,
  ...over,
});

const language = (files: FoundModel[], installed = true): LanguageState => ({
  selected: null,
  contexts: [8192],
  engine: { installed, version: null, backend: null, running: false },
  files: files.map((f) => ({ ...f, chosen: false })),
  servers: [],
});

describe("chat", () => {
  const deps = (state: LanguageState, over: { choose?: ReturnType<typeof vi.fn> } = {}) => {
    const choose = over.choose ?? vi.fn(async () => ({ selected: null }));
    return {
      choose,
      deps: {
        language: { state: async () => state, choose } as unknown as LanguageApi,
        hub: {
          state: async () => ({ enabled: false, has_token: false, shelf: [], capabilities: [] }),
        } as unknown as HubApi,
        discovery: { scan: async () => ({ running: true }) } as unknown as DiscoveryApi,
        models: {
          overview: async () => ({ ...overview([]), memory_bytes: 32e9 }),
        } as unknown as ModelsApi,
        engines: engines(true, state.engine.installed),
      },
    };
  };

  it("lists a downloaded model as ready and the rest of the shelf as to get", async () => {
    const { deps: d } = deps(language([found()]));
    const rows = (await chatChoices(d).list()).choices;
    const have = rows.find((r) => r.id === "f1");
    expect(have).toMatchObject({ state: "ready", source: "app", title: "Qwen3 4B" });
    expect(rows.some((r) => r.id === "hub:unsloth/Qwen3-4B-GGUF")).toBe(false);
    expect(rows.find((r) => r.id === "hub:unsloth/Qwen3-8B-GGUF")).toMatchObject({
      state: "needs_download",
      downloadBytes: 5e9,
    });
  });

  it("leaves search models out of a running server's list", async () => {
    const state = language([]);
    state.servers = ["gemma4:e4b", "bge-m3:latest", "nomic-embed-text:latest"].map((model) => ({
      tool: "ollama",
      title: "Ollama",
      url: "http://127.0.0.1:11434",
      model,
      chosen: false,
    }));
    const { deps: d } = deps(state);
    const rows = (await chatChoices(d).list()).choices.filter((r) => r.source === "server");
    expect(rows.map((r) => r.title)).toEqual(["gemma4:e4b"]);
  });

  it("does not fetch a model again when its files are already here", async () => {
    const download = vi.fn();
    const { deps: d, choose } = deps(language([found()]));
    d.hub = { ...d.hub, download } as unknown as HubApi;
    await chatChoices(d).get("hub:unsloth/Qwen3-4B-GGUF", () => {}, never);
    expect(download).not.toHaveBeenCalled();
    expect(choose).toHaveBeenCalledWith({ item_id: "f1", context: 8192 });
  });

  it("recommends by memory", () => {
    expect(recommendedChat(4e9)).toContain("0.6B");
    expect(recommendedChat(8e9)).toContain("4B");
    expect(recommendedChat(32e9)).toContain("8B");
  });

  it("needs the chat engine first when it is missing, even for a file already here", async () => {
    const { deps: d } = deps(language([found()], false));
    const row = (await chatChoices(d).list()).choices.find((r) => r.id === "f1");
    expect(row).toMatchObject({ state: "needs_download", engineBytes: 3e8, downloadBytes: 0 });
  });

  it("chooses a ready file with the context already in use", async () => {
    const { deps: d, choose } = deps(language([found()]));
    await chatChoices(d).choose("f1");
    expect(choose).toHaveBeenCalledWith({ item_id: "f1", context: 8192 });
  });

  const keysWith = (mode: "here" | "key") => {
    const save = vi.fn(async () => ({}));
    const keys = {
      list: async () => ({
        can_save: true,
        providers: [
          {
            id: "openrouter",
            title: "OpenRouter",
            kind: "text",
            host: "openrouter.ai",
            needs_base: false,
            models: [],
          },
        ],
        products: [
          {
            id: "chat",
            title: "Chat and writing",
            kind: "text",
            mode,
            provider: mode === "key" ? "openrouter" : null,
            model: mode === "key" ? "openai/gpt-4o-mini" : null,
            base_url: null,
            key_saved: mode === "key",
            state: mode === "key" ? "ok" : "here",
            said: null,
            tested_at: null,
            models: [],
          },
        ],
      }),
      save,
    } as unknown as OwnKeysApi;
    return { keys, save };
  };

  it("with chat on the person's key, that is the row in use and no local model is", async () => {
    const state = language([found()]);
    state.files = state.files.map((f) => ({ ...f, chosen: true }));
    const { deps: d } = deps(state);
    const rows = (await chatChoices({ ...d, keys: keysWith("key").keys }).list()).choices;
    expect(rows[0]).toMatchObject({
      id: KEYED,
      chosen: true,
      state: "ready",
      title: "openai/gpt-4o-mini · with your key · OpenRouter",
      from: "openrouter.ai",
    });
    expect(rows.filter((r) => r.chosen).map((r) => r.id)).toEqual([KEYED]);
    const here = (await chatChoices({ ...d, keys: keysWith("here").keys }).list()).choices;
    expect(here.some((r) => r.id === KEYED)).toBe(false);
  });

  it("choosing a model on this computer takes chat off the key, and the key row is a no-op", async () => {
    const { deps: d, choose } = deps(language([found()]));
    const { keys, save } = keysWith("key");
    const api = chatChoices({ ...d, keys });
    await api.choose(KEYED);
    expect(save).not.toHaveBeenCalled();
    expect(choose).not.toHaveBeenCalled();
    await api.choose("f1");
    expect(save).toHaveBeenCalledWith("chat", "here");
    expect(choose).toHaveBeenCalledWith({ item_id: "f1", context: 8192 });
  });

  it("rates fit from memory", () => {
    expect(fitOf(4, 32e9)).toBe("fits");
    expect(fitOf(6.5, 8e9)).toBe("tight");
    expect(fitOf(14, 8e9)).toBe("too_big");
    expect(fitOf(4, null)).toBeNull();
  });

  it("takes the usual 4-bit file, else the one nearest the size promised", () => {
    const v = (quant: string, size: number) => ({
      id: quant,
      name: quant,
      quant,
      files: [],
      size,
      sizes: [],
      fit: null,
    });
    expect(pickVariant([v("Q8_0", 4e9), v("Q4_K_M", 2.5e9)], 5e9)?.quant).toBe("Q4_K_M");
    expect(pickVariant([v("Q8_0", 4e9), v("Q2_K", 1.5e9)], 1.4e9)?.quant).toBe("Q2_K");
    expect(pickVariant([], 1)).toBeNull();
  });
});
