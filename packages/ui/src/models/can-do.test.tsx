// @vitest-environment jsdom
// "What this computer can do" at the top of Settings (ADR-0093, stage U11): each job in words, from the model lists.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ComputerCanDo } from "./CanDo";
import { ModelChoicesProvider } from "./context";
import type { ChoicesApi, ModelChoice } from "./types";

const row = (over: Partial<ModelChoice> = {}): ModelChoice => ({
  id: "m1",
  title: "Kokoro 82M",
  plain: "",
  tier: "recommended",
  state: "ready",
  chosen: false,
  downloadBytes: 0,
  engineBytes: 0,
  engineName: null,
  fit: "fits",
  fitReason: null,
  source: "app",
  sizeBytes: 1,
  removable: false,
  ...over,
});

function show(rows: Partial<Record<string, ModelChoice[]>>) {
  const src = (group: string): ChoicesApi => ({
    list: async () => ({ choices: rows[group] ?? [], diskFreeBytes: 87e9, memoryBytes: 69e9 }),
    choose: async () => {},
    get: async () => {},
  });
  return render(
    <ModelChoicesProvider source={src as never}>
      <ComputerCanDo />
    </ModelChoicesProvider>,
  );
}

afterEach(cleanup);

describe("what this computer can do", () => {
  it("says each job's model and whether it is ready, and the memory and disk", async () => {
    show({
      chat: [row({ id: "c", title: "qwen3.8:27b-mlx", chosen: true })],
      images: [row({ id: "i", title: "FLUX.2 klein 4B", state: "needs_download", chosen: true })],
      voice: [row()], // the voice tools use a ready model by themselves
      video: [row({ id: "v", title: "LTX-Video 2B", state: "needs_download" })],
      three_d: [row({ id: "t", title: "Pixal3D", state: "unavailable" })],
      documents: [row({ id: "d", title: "BGE small" })],
    });
    expect(await screen.findByText("Ready: Qwen3.8 27B (MLX)")).toBeInTheDocument();
    expect(screen.getByText("Needs a download: FLUX.2 klein 4B")).toBeInTheDocument();
    expect(screen.getByText("Ready: Kokoro 82M")).toBeInTheDocument();
    expect(screen.getByText("Needs a download")).toBeInTheDocument();
    expect(screen.getAllByText("Not on this computer").length).toBeGreaterThan(0);
    // a job whose model must be chosen says so, rather than ready
    expect(screen.getByText("A model is here; choose it on the model button")).toBeInTheDocument();
    expect(
      await screen.findByText("This computer: 69 GB of memory, 87 GB free on the disk."),
    ).toBeInTheDocument();
  });
});
