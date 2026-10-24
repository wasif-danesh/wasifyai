// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TrainedModel } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ImageFlowApi } from "../hooks/use-image-flow";
import { TryIt, starterPrompt } from "./TryIt";

afterEach(cleanup);

const MODEL = {
  id: "m1",
  name: "gabrin",
  trigger_word: "gabrin",
  kind: "character",
  preview: false,
  card: { published: { lora_name: "wasify-gabrin-abcd1234.safetensors" } },
} as unknown as TrainedModel;

type Input = { seed?: number; loras?: { name: string; weight: number }[]; prompt: string };

function fakeRuns(inputs: Input[], failWith?: string): ImageFlowApi {
  return {
    startRun: vi.fn(async (_product, input, _signal, onEvent) => {
      inputs.push(input as Input);
      const n = inputs.length;
      if (failWith) {
        onEvent({
          event: "done",
          data: { event: "done", outputs: { status: "refused", refusal: { message: failWith } } },
        } as never);
        return;
      }
      onEvent({
        event: "done",
        data: {
          event: "done",
          outputs: {
            status: "done",
            image_id: `i${n}`,
            image_url: `http://x/i${n}.png`,
            thumb_url: `http://x/t${n}.jpg`,
            width: 512,
            height: 512,
            prompt: (input as Input).prompt,
            mode: "text",
          },
        },
      } as never);
    }),
    watchRun: vi.fn(async () => {}),
  } as unknown as ImageFlowApi;
}

describe("Try it", () => {
  it("starts from the magic word in a scene it has not seen", () => {
    expect(starterPrompt({ kind: "character", trigger_word: "gabrin" })).toContain("gabrin");
    expect(starterPrompt({ kind: "style", trigger_word: "tazur" })).toMatch(/tazur$/);
  });

  it("draws the words twice with one seed: without the style, then with it", async () => {
    const inputs: Input[] = [];
    render(<TryIt model={MODEL} runs={fakeRuns(inputs)} />);
    await userEvent.click(screen.getByRole("button", { name: "Draw it" }));
    await waitFor(() => expect(screen.getByAltText("With gabrin")).toBeInTheDocument());
    expect(inputs).toHaveLength(2);
    expect(inputs[0]?.loras).toBeUndefined();
    expect(inputs[1]?.loras).toEqual([{ name: "wasify-gabrin-abcd1234.safetensors", weight: 1 }]);
    expect(inputs[0]?.seed).toBe(inputs[1]?.seed);
    expect(screen.getByAltText("Without gabrin")).toHaveAttribute("src", "http://x/i1.png");
    expect(screen.getByAltText("With gabrin")).toHaveAttribute("src", "http://x/i2.png");
  });

  it("says why when the picture was refused", async () => {
    render(<TryIt model={MODEL} runs={fakeRuns([], "No image model is set up.")} />);
    await userEvent.click(screen.getByRole("button", { name: "Draw it" }));
    expect(await screen.findByText("No image model is set up.")).toBeInTheDocument();
  });

  it("offers nothing for a model the image engine does not have, or a preview", () => {
    const unpublished = { ...MODEL, card: { published: null } } as unknown as TrainedModel;
    render(<TryIt model={unpublished} runs={fakeRuns([])} />);
    expect(screen.getByText(/not ready to draw with/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Draw it" })).toBeNull();
    cleanup();
    render(<TryIt model={{ ...MODEL, preview: true }} runs={fakeRuns([])} />);
    expect(screen.getByText(/preview model cannot draw/)).toBeInTheDocument();
  });
});
