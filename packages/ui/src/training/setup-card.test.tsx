// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TrainStatus, TrainingApi, TrainingSetupState } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Train } from "./Train";

afterEach(cleanup);

const STATUS = {
  ready: false,
  problem: "Training is not set up on this computer yet. Set it up first.",
  preview: false,
  engine: {},
  fit: null,
  busy: false,
  active_run: null,
  place: "device",
  min_pictures: 8,
  max_pictures: 100,
  kinds: ["character", "style", "object"],
  statements: { mine: "", permission: "", drawing: "", artwork: "" },
  base: "flux2-klein-base-4b",
  steps: { character: 200, style: 250, object: 150 },
  estimates: { character: "", style: "", object: "" },
} as unknown as TrainStatus;

const OFFER: TrainingSetupState = {
  installed: false,
  tool: null,
  base: null,
  problem: null,
  plan: {
    supported: true,
    bytes: 17_080_000_000,
    needs_free_bytes: 20_300_000_000,
    parts: [
      {
        name: "Trainer (mflux)",
        version: "0.22.0",
        bytes: 1_100_000_000,
        have: false,
        licence: "MIT",
        source: "pypi.org",
      },
      {
        name: "FLUX.2 klein base 4B",
        version: "the picture model it learns on",
        bytes: 15_980_000_000,
        have: false,
        licence: "Apache-2.0",
        source: "huggingface.co",
      },
    ],
  },
  progress: { state: "idle", step: null, steps: [], message: "", done_bytes: 0, total_bytes: 0 },
};

function api(setup: () => Promise<TrainingSetupState>, extra: Partial<TrainingApi> = {}) {
  return {
    status: async () => STATUS,
    datasets: async () => [],
    models: async () => [],
    runs: async () => [],
    setup,
    installSetup: vi.fn(async () => OFFER),
    cancelSetup: vi.fn(async () => OFFER),
    removeSetup: vi.fn(async () => ({ freed_bytes: 0, ...OFFER })),
    ...extra,
  } as unknown as TrainingApi;
}

describe("Set up training", () => {
  it("shows what will be fetched, how large and whose licence, before anything is", async () => {
    render(<Train api={api(async () => OFFER)} pollMs={10} />);
    // shown when the card's Set up asks for it (ADR-0093 U10)
    await userEvent.click(
      await screen.findByRole("button", { name: "Set up: Make my own character or style" }),
    );
    expect(await screen.findByText("Set up training")).toBeTruthy();
    expect(screen.getByText("Trainer (mflux)")).toBeTruthy();
    expect(screen.getByText(/MIT · from pypi\.org/)).toBeTruthy();
    expect(screen.getByText(/Apache-2\.0 · from huggingface\.co/)).toBeTruthy();
    expect(
      screen.getByText(/about 20\.\d GB of free disk space|about 20 GB of free disk space/),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /Download and set up/ })).toBeTruthy();
  });

  it("starts only when the button is pressed, repeating the size it showed", async () => {
    const calls = api(async () => OFFER);
    render(<Train api={calls} pollMs={10} />);
    expect(calls.installSetup).not.toHaveBeenCalled();
    await userEvent.click(
      await screen.findByRole("button", { name: "Set up: Make my own character or style" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /Download and set up/ }));
    expect(calls.installSetup).toHaveBeenCalledWith(17_080_000_000);
  });

  it("follows the install and reads training again when it is ready", async () => {
    let state: TrainingSetupState = {
      ...OFFER,
      progress: {
        state: "installing",
        step: "model",
        steps: [],
        message: "Getting the picture model",
        done_bytes: 8e9,
        total_bytes: 17e9,
      },
    };
    let statusReads = 0;
    const calls = api(async () => state, {
      status: async () => {
        statusReads++;
        return STATUS;
      },
    });
    render(<Train api={calls} pollMs={10} />);
    expect(await screen.findByText("Getting the picture model")).toBeTruthy();
    expect(screen.getByRole("progressbar", { name: "Setup progress" })).toBeTruthy();
    const before = statusReads;
    state = {
      ...OFFER,
      installed: true,
      tool: "managed",
      base: "managed",
      progress: {
        state: "ready",
        step: null,
        steps: [],
        message: "Ready",
        done_bytes: 17e9,
        total_bytes: 17e9,
      },
    };
    await waitFor(() => expect(statusReads).toBeGreaterThan(before));
  });

  it("says in words when it cannot be done on this computer, and offers nothing", async () => {
    const calls = api(async () => ({
      ...OFFER,
      problem: "Teaching a picture model works on a Mac with Apple silicon for now.",
      plan: { ...OFFER.plan, supported: false },
    }));
    render(<Train api={calls} pollMs={10} />);
    expect(await screen.findByText(/works on a Mac with Apple silicon/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Download and set up/ })).toBeNull();
  });

  it("falls back to the engine's own sentence where there is no component (the web)", async () => {
    render(
      <Train
        api={api(async () => {
          throw new Error("404");
        })}
        place="service"
        pollMs={10}
      />,
    );
    expect(await screen.findByText(/Set it up first/)).toBeTruthy();
    expect(screen.queryByText("Set up training")).toBeNull();
  });

  it("shows a failed install with its reason and lets the person try again", async () => {
    const failed: TrainingSetupState = {
      ...OFFER,
      progress: {
        state: "failed",
        step: "packages",
        steps: [],
        message: "The trainer's packages could not be installed. Are you online?",
        done_bytes: 0,
        total_bytes: 0,
      },
    };
    render(<Train api={api(async () => failed)} pollMs={10} />);
    expect(await screen.findByText(/Are you online\?/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Download and set up/ })).toBeTruthy();
  });
});
