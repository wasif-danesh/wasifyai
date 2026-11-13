import { describe, expect, it, vi } from "vitest";
import type { ModelEntry, ModelsApi } from "../models";
import { type Step, modelStep, runSteps } from "./steps";

const step = (bytes: number, label = "s"): Step => ({
  label,
  bytes,
  run: async (report) => {
    report(0.5);
    report(1);
  },
});

describe("runSteps", () => {
  it("weights each step by its bytes and ends at 1", async () => {
    const seen: (number | null)[] = [];
    await runSteps(
      [step(100, "a"), step(300, "b")],
      (p) => seen.push(p.fraction),
      new AbortController().signal,
    );
    expect(seen[0]).toBe(0);
    expect(seen).toContain(0.25); // a done, b not begun
    expect(seen).toContain(0.625); // a done, b half
    expect(seen.at(-1)).toBe(1);
  });

  it("stops between steps when stopped", async () => {
    const c = new AbortController();
    const second = vi.fn();
    await expect(
      runSteps(
        [
          { label: "a", bytes: 1, run: async () => c.abort() },
          { label: "b", bytes: 1, run: second },
        ],
        () => {},
        c.signal,
      ),
    ).rejects.toThrow("Stopped.");
    expect(second).not.toHaveBeenCalled();
  });
});

describe("modelStep", () => {
  const entry = { id: "m", title: "M", bytes_missing: 10 } as ModelEntry;
  const download = (status: string, done = 0, error = "") => ({
    id: "d1",
    entry_id: "m",
    files: [],
    bytes_total: 10,
    bytes_done: done,
    status,
    current: "",
    error,
  });

  it("starts the download and follows it to the end", async () => {
    const models = {
      start: vi.fn(async () => download("running")),
      download: vi
        .fn()
        .mockResolvedValueOnce(download("running", 5))
        .mockResolvedValue(download("done", 10)),
      cancel: vi.fn(),
    } as unknown as ModelsApi;
    const seen: number[] = [];
    await modelStep(models, entry, { pollMs: 1 }).run(
      (f) => seen.push(f),
      new AbortController().signal,
    );
    expect(seen).toEqual([0.5, 1]);
    expect(models.start).toHaveBeenCalledWith(entry, false);
  });

  it("says why a download failed", async () => {
    const models = {
      start: vi.fn(async () => download("running")),
      download: vi.fn(async () => download("failed", 0, "No space left.")),
      cancel: vi.fn(),
    } as unknown as ModelsApi;
    await expect(
      modelStep(models, entry, { pollMs: 1 }).run(() => {}, new AbortController().signal),
    ).rejects.toThrow("No space left.");
  });

  it("cancels the download when stopped", async () => {
    const c = new AbortController();
    const models = {
      start: vi.fn(async () => download("running")),
      download: vi.fn(async () => {
        c.abort();
        return download("running");
      }),
      cancel: vi.fn(async () => ({ cancelled: true })),
    } as unknown as ModelsApi;
    await expect(modelStep(models, entry, { pollMs: 1 }).run(() => {}, c.signal)).rejects.toThrow(
      "Stopped.",
    );
    expect(models.cancel).toHaveBeenCalledWith("d1");
  });
});
