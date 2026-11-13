import type { Transport } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import {
  type DownloadState,
  type ModelEntry,
  confirmationFor,
  createModelsApi,
  downloadFraction,
  missingFiles,
} from "./models";

const entry = (present: boolean[]): ModelEntry => ({
  id: "flux2-klein-4b",
  product_id: "wasifyai-image",
  title: "FLUX.2 klein 4B",
  source: "https://huggingface.co/Comfy-Org/flux2-klein-4B",
  note: "",
  approx_ram_gb: 24,
  status: "missing",
  bytes_total: 300,
  bytes_missing: 0,
  memory_warning: null,
  fit: null,
  files: present.map((p, i) => ({
    folder: "vae",
    name: `f${i}.safetensors`,
    size: 100 * (i + 1),
    present: p,
    location: null,
    removable: false,
    partial_bytes: 0,
  })),
});

describe("what a download would fetch", () => {
  it("is only the files that are missing, and their total", () => {
    const e = entry([true, false, false]);
    expect(missingFiles(e).bytes).toBe(500);
    expect(confirmationFor(e)).toEqual({ files: ["f1.safetensors", "f2.safetensors"], bytes: 500 });
    expect(confirmationFor(entry([true, true, true]))).toEqual({ files: [], bytes: 0 });
  });
});

describe("downloadFraction", () => {
  const d = (done: number, total: number): DownloadState => ({
    id: "1",
    entry_id: "x",
    files: [],
    bytes_total: total,
    bytes_done: done,
    status: "running",
    current: "",
    error: "",
  });
  it("is a share of the total, kept between 0 and 1", () => {
    expect(downloadFraction(d(50, 200))).toBe(0.25);
    expect(downloadFraction(d(0, 0))).toBe(0);
    expect(downloadFraction(d(300, 200))).toBe(1);
  });
});

describe("the models api", () => {
  function setup(answer: Response) {
    const calls: { path: string; init?: RequestInit }[] = [];
    const transport: Transport = {
      async fetch(path, init) {
        calls.push({ path, init });
        return answer.clone();
      },
    };
    return { api: createModelsApi(transport), calls };
  }

  it("starts a download with the confirmation the window showed", async () => {
    const { api, calls } = setup(Response.json({ id: "d1" }));
    await api.start(entry([false, true, false]));
    expect(calls[0]?.path).toBe("/desktop/models/flux2-klein-4b/download");
    expect(JSON.parse(calls[0]?.init?.body as string)).toEqual({
      files: ["f0.safetensors", "f2.safetensors"],
      bytes: 400,
    });
  });

  it("turns the engine's refusal into a message a person can read", async () => {
    const { api } = setup(
      Response.json({ detail: "There is not enough free space." }, { status: 409 }),
    );
    await expect(api.start(entry([false]))).rejects.toMatchObject({
      status: 409,
      message: "There is not enough free space.",
    });
  });

  it("sends folder choices as the engine expects them", async () => {
    const { api, calls } = setup(Response.json({ models_dir: "/m", extra_dirs: [] }));
    await api.setFolders("/Volumes/Big/models", ["/Users/me/ComfyUI-Shared/models"]);
    expect(calls[0]?.init?.method).toBe("PUT");
    expect(JSON.parse(calls[0]?.init?.body as string)).toEqual({
      models_dir: "/Volumes/Big/models",
      extra_dirs: ["/Users/me/ComfyUI-Shared/models"],
    });
  });
});

describe("accepting a model that will not fit", () => {
  it("sends the flag only when the person chose it", () => {
    const e = entry([false, false]);
    expect(confirmationFor(e)).not.toHaveProperty("accept_memory");
    expect(confirmationFor(e, true).accept_memory).toBe(true);
  });
});
