import type { NotebooksStatus } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import type { DownloadState, ModelEntry } from "./models";
import { SEARCH_MODEL, setupItems } from "./notebook-setup";

const entry = { id: SEARCH_MODEL, bytes_total: 67_176_520 } as unknown as ModelEntry;

function status(over: Partial<NotebooksStatus> = {}): NotebooksStatus {
  return {
    embedder: { ready: false, id: SEARCH_MODEL, size_bytes: 67_176_520 },
    reader: {
      ready: false,
      id: "docling",
      needed_for: ["pdf"],
      setup: {
        available: true,
        installed: false,
        offer: {
          id: "docling",
          size_bytes: 1_466_177_706,
          licences: "",
          source: "",
          needs_free_bytes: 3_221_225_472,
        },
        progress: {
          state: "idle",
          step: null,
          steps: [],
          message: "",
          done_bytes: 0,
          total_bytes: 0,
        },
      },
    },
    index: { chunks: 0, embedder: SEARCH_MODEL, dimension: 384 },
    ...over,
  };
}

const running = (done: number): DownloadState => ({
  id: "d",
  entry_id: SEARCH_MODEL,
  files: [],
  bytes_total: 100,
  bytes_done: done,
  status: "running",
  current: "",
  error: "",
});

describe("what a notebook still needs", () => {
  it("lists nothing until the engine has answered", () => {
    expect(setupItems(null, null, null, null)).toEqual([]);
  });

  it("offers both, with their sizes, the search model as required", () => {
    const [search, reader] = setupItems(status(), entry, null, null);
    expect(search).toMatchObject({
      id: "search",
      state: "missing",
      bytes: 67_176_520,
      required: true,
    });
    expect(reader).toMatchObject({
      id: "reader",
      state: "missing",
      bytes: 1_466_177_706,
      required: false,
    });
  });

  it("shows the download as it goes and the step of the reader's setup", () => {
    const s = status();
    if (s.reader.setup.available) {
      s.reader.setup.progress = {
        state: "installing",
        step: "weights",
        steps: [],
        message: "Downloading the reader's models",
        done_bytes: 50,
        total_bytes: 200,
      };
    }
    const [search, reader] = setupItems(s, entry, running(25), null);
    expect(search).toMatchObject({ state: "working", fraction: 0.25 });
    expect(reader).toMatchObject({
      state: "working",
      fraction: 0.25,
      message: "Downloading the reader's models",
    });
  });

  it("is ready when the engine says so, and names a failure", () => {
    const ready = status({
      embedder: { ready: true, id: SEARCH_MODEL, size_bytes: 1 },
    });
    expect(setupItems(ready, entry, null, null)[0]?.state).toBe("ready");
    const failed = setupItems(status(), entry, null, { id: "search", message: "No disk space." });
    expect(failed[0]).toMatchObject({ state: "failed", message: "No disk space." });
  });

  it("says when the reader is not part of this build", () => {
    const s = status();
    s.reader.setup = { available: false, message: "The reader is not part of this build." };
    const reader = setupItems(s, entry, null, null)[1];
    expect(reader).toMatchObject({
      state: "unavailable",
      message: "The reader is not part of this build.",
    });
    s.reader.ready = true; // installed some other way: nothing to show
    expect(setupItems(s, entry, null, null)).toHaveLength(1);
  });
});
