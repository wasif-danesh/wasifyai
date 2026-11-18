// A group's one setup (ADR-0109, stages FR2 and FR4): which item a screen is, what a press of the button runs and in
// which order, and which chat model a group gets.
import type { SetupGroup, SetupPart } from "@wasifyai/client";
import type { ModelChoice } from "@wasifyai/ui";
import { describe, expect, it, vi } from "vitest";
import { ROUTES } from "./menu";
import type { ModelEntry } from "./models";
import { chatOffer, itemOfRoute, partsToRun, stepsFor } from "./setup-groups";

const part = (over: Partial<SetupPart>): SetupPart => ({
  id: "component:audiocpp",
  kind: "component",
  ref: "audiocpp",
  title: "Speech runtime",
  bytes: 42e6,
  set_up: false,
  installing: false,
  memory_bytes: null,
  available: true,
  reason: "",
  fit: "include",
  included: true,
  items: [],
  ...over,
});

const group = (parts: SetupPart[]): SetupGroup => ({
  id: "voice",
  items: [],
  parts,
  uses: [],
  explain_only: false,
  state: "needs_setup",
  download_bytes: 0,
  download_instead_bytes: 0,
  key: { covers: false, first: false, only: false },
  memory_bytes: 8e9,
});

const choice = (over: Partial<ModelChoice>): ModelChoice => ({
  id: "qwen3-4b",
  title: "Qwen3 4B",
  plain: "",
  tier: "recommended",
  state: "needs_download",
  chosen: false,
  downloadBytes: 2.5e9,
  engineBytes: 12e6,
  engineName: null,
  fit: "fits",
  fitReason: null,
  source: "app",
  ...over,
});

describe("the item a screen is", () => {
  it("reverses the menu's routes", () => {
    expect(itemOfRoute("speak", ROUTES, null)).toBe("voice.speak");
    expect(itemOfRoute("lipsync", ROUTES, null)).toBe("voice.lipsync");
    expect(itemOfRoute("notebook", ROUTES, "new")).toBe("notebook.create");
    expect(itemOfRoute("notebook", ROUTES, "n1")).toBe("notebook.list");
    expect(itemOfRoute("home", ROUTES, null)).toBeNull();
    expect(itemOfRoute("settings", ROUTES, null)).toBeNull();
  });
});

describe("one press of the button", () => {
  const dots = part({
    id: "model:dots",
    kind: "model",
    ref: "dots",
    bytes: 2.96e9,
    fit: "on_request",
    included: false,
  });
  const kokoro = part({ id: "model:kokoro", kind: "model", ref: "kokoro", bytes: 0.19e9 });
  const big = part({
    id: "model:huge",
    kind: "model",
    ref: "huge",
    fit: "cannot_run",
    included: false,
  });
  const done = part({ id: "component:comfyui", ref: "comfyui", set_up: true });

  it("runs the group's download, small parts first, and skips what is set up", () => {
    const run = partsToRun(group([kokoro, dots, part({}), big, done]), false);
    expect(run.map((p) => p.id)).toEqual(["component:audiocpp", "model:kokoro"]);
  });

  it("adds what only Download instead fetches, never what cannot run", () => {
    const run = partsToRun(group([kokoro, dots, part({}), big]), true);
    expect(run.map((p) => p.id)).toEqual(["component:audiocpp", "model:kokoro", "model:dots"]);
  });

  it("makes a step per part through the route that sets it up", async () => {
    const installs: string[] = [];
    const accepted: boolean[] = [];
    const entry = (id: string) => ({ id, bytes_missing: 1 }) as unknown as ModelEntry;
    const steps = await stepsFor(group([kokoro, dots, part({})]), true, {
      components: {
        status: async () => ({ state: "not_installed", needs_bytes: 42e6 }),
        install: async (id) => {
          installs.push(id);
        },
        onStatus: async () => () => {},
      },
      models: {
        entry: async (id) => entry(id),
        step: (e, accept) => {
          accepted.push(accept);
          return { label: e.id, bytes: 1, run: async () => {} };
        },
      },
      chat: null,
    });
    expect(steps.map((s) => s.label)).toEqual(["Setting up Speech runtime", "kokoro", "dots"]);
    // a model only "Download instead" fetches goes past the memory warning: the card said so
    expect(accepted).toEqual([false, true]);
  });
});

describe("the chat model a group gets", () => {
  it("uses one already on the computer before downloading one", () => {
    const found = choice({ id: "ollama:qwen3:8b", state: "ready", source: "server" });
    expect(chatOffer([choice({}), found])?.id).toBe("ollama:qwen3:8b");
  });

  it("else offers the recommended one", () => {
    expect(chatOffer([choice({ tier: "also", id: "x" }), choice({})])?.id).toBe("qwen3-4b");
  });

  it("offers nothing when a chat model is in use", () => {
    expect(chatOffer([choice({ chosen: true, state: "ready" })])).toBeNull();
  });

  it("runs the chat choice's get and use", async () => {
    const get = vi.fn(async () => {});
    const steps = await stepsFor(group([part({ id: "chat", kind: "chat", ref: "" })]), false, {
      components: {
        status: async () => ({ state: "installed", version: "", accelerator: "" }),
        install: async () => {},
        onStatus: async () => () => {},
      },
      models: {
        entry: async () => null,
        step: () => ({ label: "", bytes: 1, run: async () => {} }),
      },
      chat: {
        list: async () => ({ choices: [choice({})], diskFreeBytes: 1e11, memoryBytes: 8e9 }),
        choose: async () => {},
        get,
      },
    });
    expect(steps[0]?.label).toBe("Setting up Qwen3 4B");
    await steps[0]?.run(() => {}, new AbortController().signal);
    expect(get).toHaveBeenCalledWith("qwen3-4b", expect.any(Function), expect.any(AbortSignal));
  });
});
