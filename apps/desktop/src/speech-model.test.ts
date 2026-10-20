// SPDX-License-Identifier: AGPL-3.0-only
import { describe, expect, it, vi } from "vitest";
import type { DownloadState, ModelEntry } from "./models";
import { getSpeechModel } from "./speech-model";

const file = {
  folder: "audio",
  name: "p.gguf",
  size: 100,
  present: false,
  location: null,
  removable: false,
  partial_bytes: 0,
};
const entry = (status: ModelEntry["status"]): ModelEntry =>
  ({
    id: "parakeet",
    status,
    files: [file],
    bytes_total: 100,
    bytes_missing: 100,
  }) as unknown as ModelEntry;
const dl = (status: DownloadState["status"], done: number, error = ""): DownloadState => ({
  id: "d1",
  entry_id: "parakeet",
  files: ["p.gguf"],
  bytes_total: 100,
  bytes_done: done,
  status,
  current: "",
  error,
});

describe("getSpeechModel", () => {
  it("asks with the files and size the card showed, then follows the download to its end", async () => {
    const start = vi.fn(async () => dl("running", 0));
    const states = [dl("running", 40), dl("done", 100)];
    const api = {
      overview: async () => ({ models: [entry("missing")] }) as never,
      start,
      download: vi.fn(async () => states.shift() as DownloadState),
    };
    const seen: number[] = [];
    await getSpeechModel(
      api,
      "parakeet",
      (f) => seen.push(f),
      async () => {},
    );
    expect(start).toHaveBeenCalledWith(expect.objectContaining({ id: "parakeet" }));
    expect(seen).toEqual([0, 0.4, 1]);
  });

  it("does nothing when the model is already here", async () => {
    const start = vi.fn();
    await getSpeechModel(
      { overview: async () => ({ models: [entry("ready")] }) as never, start, download: vi.fn() },
      "parakeet",
      () => {},
    );
    expect(start).not.toHaveBeenCalled();
  });

  it("says what went wrong in words", async () => {
    const api = {
      overview: async () => ({ models: [entry("missing")] }) as never,
      start: async () => dl("failed", 10, "There is not enough disk space."),
      download: vi.fn(),
    };
    await expect(getSpeechModel(api, "parakeet", () => {})).rejects.toThrow(
      "not enough disk space",
    );
    await expect(
      getSpeechModel({ ...api, overview: async () => ({ models: [] }) as never }, "x", () => {}),
    ).rejects.toThrow("not one this app knows");
  });
});
