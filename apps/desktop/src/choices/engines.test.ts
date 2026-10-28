import { describe, expect, it, vi } from "vitest";
import type { ComponentStatus } from "../engine";
import { type ComponentPort, createEngines, stateOf } from "./engines";

const progress = {
  component: "comfyui",
  step: "s",
  label: "Installing",
  index: 1,
  count: 2,
  bytes_done: 0,
  bytes_total: 10,
  detail: null,
};

describe("stateOf", () => {
  it("reads what the shell reports", () => {
    expect(stateOf({ state: "installed", version: "1", accelerator: "mps" }, "E").installed).toBe(
      true,
    );
    expect(stateOf({ state: "not_installed", needs_bytes: 5 }, "E")).toMatchObject({
      installed: false,
      bytes: 5,
      supported: true,
    });
    expect(stateOf({ state: "unsupported", reason: "x" }, "E").supported).toBe(false);
  });
});

describe("the image engine step", () => {
  function port(first: ComponentStatus) {
    let push: (id: string, s: ComponentStatus) => void = () => {};
    const p: ComponentPort = {
      status: vi.fn(async () => first),
      install: vi.fn(async () => {
        push("comfyui", { state: "installing", progress });
        push("comfyui", { state: "installed", version: "1", accelerator: "mps" });
      }),
      onStatus: async (fn) => {
        push = fn;
        return () => {};
      },
    };
    return p;
  }

  it("starts the set-up and waits for it", async () => {
    const p = port({ state: "not_installed", needs_bytes: 7 });
    const step = await createEngines(p).imageStep();
    expect(step.bytes).toBe(7);
    await step.run(() => {}, new AbortController().signal);
    expect(p.install).toHaveBeenCalledWith("comfyui", 7); // with the size the dialog showed
  });

  it("does nothing when it is there already", async () => {
    const p = port({ state: "installed", version: "1", accelerator: "mps" });
    await (await createEngines(p).imageStep()).run(() => {}, new AbortController().signal);
    expect(p.install).not.toHaveBeenCalled();
  });

  it("reports a set-up that failed", async () => {
    const p = port({ state: "not_installed", needs_bytes: 7 });
    p.install = vi.fn(async () => {
      // the fake's listener is registered by then
      await p.onStatus(() => {});
    });
    let fail: (id: string, s: ComponentStatus) => void = () => {};
    p.onStatus = async (fn) => {
      fail = fn;
      return () => {};
    };
    p.install = vi.fn(async () =>
      fail("comfyui", { state: "failed", message: "No disk.", step: null }),
    );
    const step = await createEngines(p).imageStep();
    await expect(step.run(() => {}, new AbortController().signal)).rejects.toThrow("No disk.");
  });
});
