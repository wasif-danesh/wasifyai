import type { OwnKeysApi, VoiceApi, VoiceModelInfo } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import type { DiscoveryApi, DiscoveryState, FoundModel } from "../discovery";
import type { HubApi } from "../hub";
import type { LanguageApi, LanguageState } from "../language";
import type { ModelEntry, ModelsApi } from "../models";
import { CATALOGUE_GROUPS, catalogueChoices } from "./catalogue-choices";
import { chatChoices, fitOf, pickVariant } from "./chat-choices";
import { recommendedChat } from "./copy";
import { model3dChoices } from "./model3d-choices";
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

/** A fake of the keys API: `product` has fal.ai models `models`, `inUse` the one it runs on (null: this computer). */
function cloudKeys(product: string, models: string[], inUse: string | null) {
  const use = vi.fn(async () => ({ product, models: [], has_keys: true }));
  const keys = {
    list: async () => ({
      can_save: true,
      providers: [],
      products: [
        {
          id: product,
          title: product,
          kind: "media",
          providers: ["fal"],
          keys: [],
          use: inUse ? { provider: "fal", model: inUse, title: inUse, price: "" } : null,
        },
      ],
    }),
    cloud: async (p: string) => ({
      product: p,
      has_keys: p === product,
      models:
        p === product
          ? models.map((m) => ({
              provider: "fal",
              provider_title: "fal.ai",
              host: "fal.ai",
              model: m,
              title: `Model ${m}`,
              about: "It makes things.",
              price: "$1 each",
              works: true,
              chosen: m === inUse,
            }))
          : [],
    }),
    use,
  } as unknown as OwnKeysApi;
  return { keys, use };
}

describe("images and video", () => {
  it("with images on a cloud model, that row is in use even with no image engine here", async () => {
    const models = {
      overview: async () => overview([entry({ status: "missing", bytes_missing: 9e9 })]),
    } as unknown as ModelsApi;
    const { keys } = cloudKeys("images", ["fal-ai/flux-2"], "fal-ai/flux-2");
    const deps = { models, engines: engines(false), memory: memory(), keys };
    const api = catalogueChoices(deps, CATALOGUE_GROUPS.images);
    expect(api.cloud?.product).toBe("Images");
    const rows = (await api.list()).choices;
    expect(rows.find((r) => r.place === "cloud")).toMatchObject({
      id: "cloud:images:fal:fal-ai/flux-2",
      chosen: true,
      state: "ready",
      title: "Model fal-ai/flux-2",
      providerTitle: "fal.ai",
      price: "$1 each",
    });
    expect(rows.filter((r) => r.chosen)).toHaveLength(1);
    // video follows its own setting, which is on this computer
    const video = (await catalogueChoices(deps, CATALOGUE_GROUPS.video).list()).choices;
    expect(video.some((r) => r.place === "cloud")).toBe(false);
  });

  it("choosing a cloud row uses it; one on this computer takes images off the cloud", async () => {
    const models = {
      overview: async () => overview([entry({ status: "ready", bytes_missing: 0 })]),
    } as unknown as ModelsApi;
    const { keys, use } = cloudKeys("images", ["fal-ai/flux-2"], "fal-ai/flux-2");
    const mem = memory();
    const api = catalogueChoices(
      { models, engines: engines(true), memory: mem, keys },
      CATALOGUE_GROUPS.images,
    );
    await api.choose("cloud:images:fal:fal-ai/flux-2");
    expect(use).toHaveBeenCalledWith("images", { provider: "fal", model: "fal-ai/flux-2" });
    await api.choose(entry({}).id);
    expect(use).toHaveBeenLastCalledWith("images", null);
  });

  it("tells the engine which model is chosen, once, so what it makes on its own uses it", async () => {
    const choose = vi.fn(async (product: string, id: string) => ({
      product_id: product,
      chosen: id,
    }));
    const ready = entry({ status: "ready", bytes_missing: 0 });
    const models = { overview: async () => overview([ready]), choose } as unknown as ModelsApi;
    const api = catalogueChoices(
      { models, engines: engines(true), memory: memory() },
      CATALOGUE_GROUPS.images,
    );
    await api.list(); // a choice made before the engine kept one is told when the list shows it
    await api.list();
    await new Promise((r) => setTimeout(r, 0));
    expect(choose).toHaveBeenCalledTimes(1);
    expect(choose).toHaveBeenCalledWith("wasifyai-image", ready.id);
    await api.choose("other-model");
    await new Promise((r) => setTimeout(r, 0));
    expect(choose).toHaveBeenLastCalledWith("wasifyai-image", "other-model");
    const docs = catalogueChoices(
      { models, engines: engines(true), memory: memory() },
      CATALOGUE_GROUPS.documents,
    );
    await docs.choose("bge-small-en-v1.5");
    await new Promise((r) => setTimeout(r, 0));
    expect(choose).toHaveBeenCalledTimes(2); // the documents' model is not an image or video model
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

  // a fresh install offered 16 GB of downloads for klein and LTX while ComfyUI's folder had the files (2026-11-04)
  const kleinFiles = (present: boolean) =>
    ["flux-2-klein-4b.safetensors", "flux2-vae.safetensors"].map((name) => ({
      folder: name.includes("vae") ? "vae" : "diffusion_models",
      name,
      size: 5e9,
      present,
      location: null,
      removable: false,
      partial_bytes: 0,
    }));
  const inComfy = (name: string, over: Partial<FoundModel> = {}) =>
    found({
      id: `c-${name}`,
      name: name.replace(".safetensors", ""),
      kind: "diffusion",
      path: `/Users/x/ComfyUI-Shared/models/some/${name}`,
      tool: "comfyui",
      tool_title: "ComfyUI",
      use_root: "/Users/x/ComfyUI-Shared/models",
      use: "folder",
      ...over,
    });
  const discovery = (items: FoundModel[]) => {
    const use = vi.fn(async () => ({ folder: "/Users/x/ComfyUI-Shared/models" }));
    return {
      api: { state: async () => ({ items }) as unknown as DiscoveryState, use },
      use,
    };
  };

  it("a model whose missing files another tool has is found there, with nothing to download", async () => {
    const models = {
      overview: async () => overview([entry({ files: kleinFiles(false) })]),
    } as unknown as ModelsApi;
    const d = discovery([inComfy("flux-2-klein-4b.safetensors"), inComfy("flux2-vae.safetensors")]);
    const list = await catalogueChoices(
      { models, engines: engines(), memory: memory(), discovery: d.api },
      CATALOGUE_GROUPS.images,
    ).list();
    expect(list.choices[0]).toMatchObject({
      state: "needs_download",
      foundIn: "ComfyUI",
      downloadBytes: 0,
      sizeBytes: 10e9,
    });
  });

  it("is not offered as found when one file is still nowhere, or the found file cannot be used", async () => {
    const models = {
      overview: async () => overview([entry({ files: kleinFiles(false) })]),
    } as unknown as ModelsApi;
    for (const items of [
      [inComfy("flux-2-klein-4b.safetensors")],
      [
        inComfy("flux-2-klein-4b.safetensors"),
        inComfy("flux2-vae.safetensors", { state: "unsupported" }),
      ],
    ]) {
      const list = await catalogueChoices(
        { models, engines: engines(), memory: memory(), discovery: discovery(items).api },
        CATALOGUE_GROUPS.images,
      ).list();
      expect(list.choices[0]?.foundIn ?? null).toBeNull();
      expect(list.choices[0]?.downloadBytes).toBe(10e9);
    }
  });

  it("getting a found model adds its folder once and downloads nothing", async () => {
    let used = false;
    const download = vi.fn();
    const models = {
      overview: async () =>
        overview([
          used
            ? entry({ status: "ready", files: kleinFiles(true), bytes_missing: 0 })
            : entry({ files: kleinFiles(false) }),
        ]),
      download,
    } as unknown as ModelsApi;
    const d = discovery([inComfy("flux-2-klein-4b.safetensors"), inComfy("flux2-vae.safetensors")]);
    d.use.mockImplementation(async () => {
      used = true;
      return { folder: "/Users/x/ComfyUI-Shared/models" };
    });
    const mem = memory();
    const labels: string[] = [];
    await catalogueChoices(
      { models, engines: engines(), memory: mem, discovery: d.api },
      CATALOGUE_GROUPS.images,
    ).get("flux2-klein-4b", (p) => labels.push(p.label), never);
    expect(d.use).toHaveBeenCalledTimes(1);
    expect(download).not.toHaveBeenCalled();
    expect(labels[0]).toBe("Using the files found in ComfyUI");
    expect(mem.data["wasifyai:model:images"]).toBe("flux2-klein-4b");
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

/** Settings › Your keys with fal.ai keys for one product: its cloud rows, and the one in use (or none). */
function onKey(product: string, model: string, mode: "here" | "key" = "key") {
  return cloudKeys(product, [model], mode === "key" ? model : null);
}

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

  it("with Voice on the person's key, speaking shows that row in use, once", async () => {
    const local = voiceModel({
      id: "kokoro-82m",
      tasks: ["speak"],
      recommended: ["speak"],
      state: "ready",
    });
    // the engine lists the cloud model for the speech screen; the picker shows the cloud rows instead
    const keyed = voiceModel({
      id: "key:voice",
      tasks: ["speak"],
      state: "ready",
      engine: "remote",
    });
    const { keys, use } = onKey("voice", "fal-ai/kokoro");
    const api = voiceChoices(
      { voice: voice([keyed, local]), models, memory: memory(), engines: engines(), keys },
      "voice",
      "speak",
    );
    const rows = (await api.list()).choices;
    expect(rows.map((r) => [r.id, r.chosen])).toEqual([
      ["kokoro-82m", false],
      ["cloud:voice:fal:fal-ai/kokoro", true],
    ]);
    // the screen knows it by the engine's id while it is in use
    expect(rows[1]?.engineId).toBe("key:voice");
    expect(rows[1]?.plain).toContain("the words it speaks");
    await api.choose("cloud:voice:fal:fal-ai/kokoro");
    expect(use).toHaveBeenCalledWith("voice", { provider: "fal", model: "fal-ai/kokoro" });
    await api.choose("kokoro-82m"); // a model on this computer takes Voice off the cloud
    expect(use).toHaveBeenLastCalledWith("voice", null);
  });

  it("listening and the other voice tools do not follow the Voice key", async () => {
    const { keys, use } = onKey("voice", "fal-ai/kokoro");
    const ready = [voiceModel({ id: "a", state: "ready" })];
    const api = voiceChoices(
      { voice: voice(ready), models, memory: memory(), engines: engines(), keys },
      "listening",
      "transcribe",
    );
    expect(api.cloud).toBeUndefined();
    expect((await api.list()).choices.some((r) => r.place === "cloud")).toBe(false);
    await api.choose("a");
    expect(use).not.toHaveBeenCalled();
  });

  it("lip sync lists its cloud models and a cloud model of music is chosen for music", async () => {
    const { keys, use } = cloudKeys(
      "lipsync",
      ["fal-ai/infinitalk", "fal-ai/longcat-single-avatar/image-audio-to-video"],
      null,
    );
    const local = voiceModel({ id: "echomimic", tasks: ["lipsync"], state: "ready" });
    const api = voiceChoices(
      { voice: voice([local]), models, memory: memory(), engines: engines(), keys },
      "faces",
      "lipsync",
    );
    expect(api.cloud?.product).toBe("Lip sync");
    const rows = (await api.list()).choices;
    expect(rows.filter((r) => r.place === "cloud").map((r) => [r.id, r.engineId])).toEqual([
      ["cloud:lipsync:fal:fal-ai/infinitalk", "key:lipsync"],
      ["cloud:lipsync:fal:fal-ai/longcat-single-avatar/image-audio-to-video", "key:lipsync"],
    ]);
    await api.choose("cloud:lipsync:fal:fal-ai/infinitalk");
    expect(use).toHaveBeenCalledWith("lipsync", { provider: "fal", model: "fal-ai/infinitalk" });
  });
});

describe("3D", () => {
  const component = (over: Record<string, unknown> = {}) => ({
    installed: false,
    source: null,
    plan: { supported: true, platform: "darwin-arm64", bytes: 7e9, parts: [], found: null },
    progress: { state: "idle", message: "", done_bytes: 0, total_bytes: 0 },
    fit: null,
    about: { built_with: "", where: "" },
    ...over,
  });
  const api3d = (c: ReturnType<typeof component>) =>
    ({ component: async () => c }) as unknown as Parameters<typeof model3dChoices>[0];

  it("with 3D on a cloud model, that row is in use and this computer's is still to set up", async () => {
    const { keys, use } = onKey("model3d", "fal-ai/pixal3d");
    // the engine says installed for the 3D screen while on the key; `here` is this computer
    const api = model3dChoices(
      api3d(component({ installed: true, here: false, keyed: true })),
      keys,
    );
    const rows = (await api.list()).choices;
    expect(rows.map((r) => [r.id, r.chosen, r.state])).toEqual([
      ["pixal3d", false, "needs_download"],
      ["cloud:model3d:fal:fal-ai/pixal3d", true, "ready"],
    ]);
    await api.choose("pixal3d");
    expect(use).toHaveBeenCalledWith("model3d", null);
  });

  it("on this computer its row is in use and the cloud one is only offered", async () => {
    const { keys } = onKey("model3d", "fal-ai/pixal3d", "here");
    const rows = (await model3dChoices(api3d(component({ installed: true })), keys).list()).choices;
    // the key is saved, so its model is offered under Cloud, but this computer's is the one in use
    expect(rows.map((r) => [r.id, r.chosen, r.state])).toEqual([
      ["pixal3d", true, "ready"],
      ["cloud:model3d:fal:fal-ai/pixal3d", false, "ready"],
    ]);
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

  const chatKeys = (inUse: boolean) =>
    cloudKeys("chat", ["openai/gpt-4o-mini"], inUse ? "openai/gpt-4o-mini" : null);
  const CLOUD_ROW = "cloud:chat:fal:openai/gpt-4o-mini";

  it("with chat on a cloud model, that is the row in use and no local model is", async () => {
    const state = language([found()]);
    state.files = state.files.map((f) => ({ ...f, chosen: true }));
    const { deps: d } = deps(state);
    const rows = (await chatChoices({ ...d, keys: chatKeys(true).keys }).list()).choices;
    expect(rows.find((r) => r.place === "cloud")).toMatchObject({
      id: CLOUD_ROW,
      chosen: true,
      state: "ready",
      from: "fal.ai",
    });
    expect(rows.filter((r) => r.chosen).map((r) => r.id)).toEqual([CLOUD_ROW]);
    const here = (await chatChoices({ ...d, keys: chatKeys(false).keys }).list()).choices;
    expect(here.filter((r) => r.chosen).map((r) => r.id)).toEqual(["f1"]);
  });

  it("choosing a cloud row uses it; a model on this computer takes chat off the cloud", async () => {
    const { deps: d, choose } = deps(language([found()]));
    const { keys, use } = chatKeys(true);
    const api = chatChoices({ ...d, keys });
    await api.choose(CLOUD_ROW);
    expect(use).toHaveBeenCalledWith("chat", { provider: "fal", model: "openai/gpt-4o-mini" });
    expect(choose).not.toHaveBeenCalled();
    await api.choose("f1");
    expect(use).toHaveBeenLastCalledWith("chat", null);
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
