import type { TrainedModel } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
// a static import: vi.mock is hoisted above it, and loading the screen stays out of each test's 5 s
import { presetForModel } from "./Train";

const list = vi.fn();
vi.mock("../api", () => ({ client: {}, stylesApi: { list: () => list() } }));
vi.mock("../training", () => ({ training: {} }));

const model = { kind: "style", trigger_word: "ena", run_id: "b37ba287-1234-5678" } as TrainedModel;
const style = (id: string, source: object) => ({ id, source });

describe("Use in Create", () => {
  it("chooses Train's style by its run, and puts the word in the prompt", async () => {
    list.mockResolvedValue({
      styles: [style("x", { kind: "file" }), style("e1", { kind: "trained", run: "b37ba287" })],
    });
    const preset = await presetForModel(model);
    expect(preset.styles).toEqual([{ id: "e1", strength: 1 }]);
    expect(preset.prompt).toMatch(/ena$/);
    expect(preset.seed).toBeNull();
  });

  it("still opens Create when the style is not found", async () => {
    list.mockRejectedValue(new Error("engine away"));
    expect((await presetForModel(model)).styles).toEqual([]);
  });
});
