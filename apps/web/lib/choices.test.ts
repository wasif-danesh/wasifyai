import type { FetchJob, VoiceApi, VoiceModelInfo, WorkerInfo, WorkersApi } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { GROUP_TASKS, choiceKey, webChoices, webChoicesFor, webRow } from "./choices";

const never = new AbortController().signal;

function model(over: Partial<VoiceModelInfo> = {}): VoiceModelInfo {
  return {
    id: "kokoro-82m",
    title: "Kokoro",
    licence: "Apache-2.0",
    engine: "audio.cpp",
    tasks: ["speak"],
    recommended: ["speak"],
    commercial_use: "yes",
    licence_evidence: "https://x/licence",
    state: "ready",
    runtime_ready: true,
    bytes_missing: 0,
    ...over,
  } as VoiceModelInfo;
}

function memory() {
  const data: Record<string, string> = {};
  return {
    data,
    get: (k: string) => data[k] ?? null,
    set: (k: string, v: string) => {
      data[k] = v;
    },
  };
}

function rig(
  models: VoiceModelInfo[],
  opts: { isAdmin?: boolean; lipsync?: WorkerInfo["lipsync_engine"] } = {},
) {
  const mem = memory();
  const jobs: FetchJob[] = [
    { status: "working", fraction: 0.5, label: "Downloading", error: null },
    { status: "done", fraction: 1, label: "", error: null },
  ];
  const workers = {
    list: vi.fn(async () => [{ id: "w1", lipsync_engine: opts.lipsync ?? null } as WorkerInfo]),
    fetchModel: vi.fn(async () => "job-model"),
    fetchEngine: vi.fn(async () => "job-engine"),
    job: vi.fn(
      async (_id: string): Promise<FetchJob> =>
        jobs.shift() ?? { status: "done", fraction: 1, label: "", error: null },
    ),
  } satisfies WorkersApi;
  const voice = { models: vi.fn(async () => models) } as unknown as VoiceApi;
  const deps = { voice, workers, memory: mem, isAdmin: opts.isAdmin ?? true };
  return { deps, mem, workers };
}

const FLUX = {
  id: "wasifyai-image:0",
  title: "FLUX.2 klein 4B",
  plain: "Set up on this service by an admin.",
  ready: true,
  licence: "Apache-2.0",
};

/** What the service says it uses, and what the 3D worker says; with the voice rig's other dependencies. */
function inUseRig(
  over: { images?: (typeof FLUX)[]; video?: (typeof FLUX)[]; threeD?: boolean } = {},
) {
  const base = rig([]).deps;
  const deps = {
    ...base,
    inUse: {
      inUse: vi.fn(async () => ({
        chat: [{ ...FLUX, id: "default-chat", title: "gemma4:e4b", licence: "" }],
        images: over.images ?? [FLUX],
        video: over.video ?? [],
      })),
    },
    model3d: {
      component: vi.fn(async () => ({ installed: over.threeD ?? true, about: { licence: "MIT" } })),
    } as never,
  };
  return deps;
}

describe("the picker on the web", () => {
  it("is there for the groups the workers serve, and for what the service uses; not for documents", () => {
    const source = webChoices(inUseRig());
    for (const g of [...Object.keys(GROUP_TASKS), "images", "video", "chat", "three_d"])
      expect(source(g as never), g).not.toBeNull();
    expect(source("documents")).toBeNull();
  });

  it("shows the model the service uses for images, chat and 3D, and nothing to choose or get", async () => {
    const source = webChoices(inUseRig());
    const images = await source("images")?.list();
    expect(images?.choices.map((c) => [c.title, c.state, c.chosen])).toEqual([
      ["FLUX.2 klein 4B", "ready", true],
    ]);
    const chat = await source("chat")?.list();
    expect(chat?.choices[0]?.title).toBe("gemma4:e4b");
    const three = await source("three_d")?.list();
    expect(three?.choices.map((c) => [c.title, c.state])).toEqual([["Pixal3D", "ready"]]);
    await expect(source("images")?.get("x", () => {}, never)).rejects.toThrow(/Ask an admin/);
  });

  it("says a model is not set up when the service has none ready, and shows none when it lists none", async () => {
    const source = webChoices(inUseRig({ images: [{ ...FLUX, ready: false }], threeD: false }));
    const images = await source("images")?.list();
    expect(images?.choices.map((c) => [c.state, c.chosen])).toEqual([["unavailable", false]]);
    const three = await source("three_d")?.list();
    expect(three?.choices[0]?.state).toBe("unavailable");
    const video = await source("video")?.list();
    expect(video?.choices).toEqual([]);
  });

  it("lists a model that is on the worker as ready and the one in use as chosen", async () => {
    const { deps } = rig([model(), model({ id: "voxcpm2", title: "VoxCPM2", state: "ready" })]);
    const list = await webChoicesFor(deps, "voice", "speak").list();
    expect(list.choices.map((c) => [c.id, c.state, c.chosen])).toEqual([
      ["kokoro-82m", "ready", true],
      ["voxcpm2", "ready", false],
    ]);
    expect(list.choices[0]?.plain).toMatch(/voice/i);
  });

  it("offers a missing model to an admin with its size, and asks anyone else to ask an admin", () => {
    const missing = model({ id: "voxcpm2", state: "can_install", bytes_missing: 4e9 });
    const admin = webRow(missing, ["speak"], null, true, null);
    expect(admin.state).toBe("needs_download");
    expect(admin.downloadBytes).toBe(4e9);
    const person = webRow(missing, ["speak"], null, false, null);
    expect(person.state).toBe("unavailable");
    expect(person.unavailableReason).toMatch(/ask an admin/i);
  });

  it("says plainly when the worker's speech engine is missing, and when lip sync cannot run", () => {
    const noRuntime = model({ state: "can_install", runtime_ready: false });
    expect(webRow(noRuntime, ["speak"], null, true, null).unavailableReason).toMatch(
      /speech engine/,
    );
    const lipsync = model({
      id: "musetalk-v15",
      engine: "sidecar",
      state: "can_install",
      runtime_ready: false,
    });
    const none = webRow(lipsync, ["lipsync"], null, true, {
      installed: false,
      supported: false,
      bytes: 9,
    });
    expect(none.unavailableReason).toMatch(/cannot run lip sync/);
    const can = webRow(lipsync, ["lipsync"], null, true, {
      installed: false,
      supported: true,
      bytes: 9e8,
    });
    expect(can.state).toBe("needs_download");
    expect(can.engineBytes).toBe(9e8);
    expect(can.engineName).toBe("The lip sync engine");
  });

  it("marks a model that is not for commercial use as advanced", () => {
    const row = webRow(model({ commercial_use: "no" }), ["speak"], null, true, null);
    expect(row.tier).toBe("advanced");
    expect(row.commercial).toBe("no");
  });

  it("remembers the choice under the key the voice screens read", async () => {
    const { deps, mem } = rig([model()]);
    await webChoicesFor(deps, "voice", "speak").choose("kokoro-82m");
    expect(mem.data[choiceKey("speak")]).toBe("kokoro-82m");
    expect(choiceKey("speak")).toBe("wasifyai.voice.model.speak");
  });

  it("gets a model through the worker, follows the job, then chooses it", async () => {
    const { deps, mem, workers } = rig([
      model({ id: "voxcpm2", state: "can_install", tasks: ["speak"] }),
    ]);
    const told: number[] = [];
    await webChoicesFor(deps, "voice", "speak").get(
      "voxcpm2",
      (p) => told.push(p.fraction ?? 0),
      never,
    );
    expect(workers.fetchModel).toHaveBeenCalledWith("voxcpm2");
    expect(workers.fetchEngine).not.toHaveBeenCalled();
    expect(told).toEqual([0.5, 1]);
    expect(mem.data[choiceKey("speak")]).toBe("voxcpm2");
  });

  it("sets up the lip sync engine first when the model needs it", async () => {
    const lipsync = { installed: false, supported: true, bytes: 9e8 };
    const { deps, workers } = rig(
      [
        model({
          id: "musetalk-v15",
          engine: "sidecar",
          state: "can_install",
          runtime_ready: false,
          tasks: ["lipsync"],
          recommended: ["lipsync"],
        }),
      ],
      { lipsync },
    );
    await webChoicesFor(deps, "faces", "lipsync").get("musetalk-v15", () => {}, never);
    expect(workers.fetchEngine).toHaveBeenCalledWith("lipsync-engine");
    expect(workers.fetchModel).toHaveBeenCalledWith("musetalk-v15");
  });

  it("does not let anyone but an admin start a fetch", async () => {
    const { deps, workers } = rig([model({ id: "voxcpm2", state: "can_install" })], {
      isAdmin: false,
    });
    await expect(
      webChoicesFor(deps, "voice", "speak").get("voxcpm2", () => {}, never),
    ).rejects.toThrow(/ask an admin/i);
    expect(workers.fetchModel).not.toHaveBeenCalled();
  });

  it("says why when the worker's job fails", async () => {
    const { deps, workers } = rig([model({ id: "voxcpm2", state: "can_install" })]);
    workers.job.mockResolvedValueOnce({
      status: "failed",
      fraction: 0,
      label: "",
      error: "No space left.",
    });
    await expect(
      webChoicesFor(deps, "voice", "speak").get("voxcpm2", () => {}, never),
    ).rejects.toThrow("No space left.");
  });
});
