// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CheckStep, TrainedModel, TrainingApi } from "@wasifyai/client";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ImageFlowApi } from "../hooks/use-image-flow";
import { CheckIt, EvaluationLine } from "./CheckIt";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  vi.stubGlobal("fetch", async () => ({
    blob: async () => new Blob(["x"], { type: "image/png" }),
  }));
});

const MODEL = {
  id: "m1",
  name: "gabrin",
  trigger_word: "gabrin",
  kind: "character",
  preview: false,
  card: {
    published: { lora_name: "wasify-gabrin-1.safetensors" },
    evaluation: { passed: null, note: "Not evaluated yet." },
  },
} as unknown as TrainedModel;

const PLAN: CheckStep[] = ["with_word", "without_word", "without_model"].map((c, n) => ({
  id: `s0-${c}`,
  scene: 0,
  condition: c as CheckStep["condition"],
  prompt: c === "without_word" ? "someone in a park" : "gabrin, in a park",
  with_model: c !== "without_model",
}));

type Input = { seed?: number; loras?: unknown[]; prompt: string };

function runs(inputs: Input[]): ImageFlowApi {
  return {
    startRun: vi.fn(async (_p, input, _s, onEvent) => {
      inputs.push(input as Input);
      onEvent({
        event: "done",
        data: {
          event: "done",
          outputs: {
            status: "done",
            image_id: `i${inputs.length}`,
            image_url: `http://x/i${inputs.length}.png`,
            thumb_url: "",
            width: 512,
            height: 512,
            prompt: "p",
            mode: "text",
          },
        },
      } as never);
    }),
    watchRun: vi.fn(async () => {}),
  } as unknown as ImageFlowApi;
}

function api(over: Partial<TrainingApi> = {}) {
  return {
    checkPlan: vi.fn(async () => ({ items: PLAN, refs: 3 })),
    judge: vi.fn(async (_id: string, _b: Blob) => ({ same: true, reason: "x" })),
    saveEvaluation: vi.fn(async (_id: string, items) => ({
      ...MODEL,
      card: {
        ...MODEL.card,
        evaluation: { passed: true, note: `Judged ${items.length}.`, at: "now" },
      },
    })),
    ...over,
  } as unknown as TrainingApi;
}

describe("Did it learn?", () => {
  it("draws each scene three ways from one seed, judges each, and keeps the result", async () => {
    const inputs: Input[] = [];
    const calls = api();
    const saved = vi.fn();
    render(<CheckIt model={MODEL} api={calls} runs={runs(inputs)} onSaved={saved} />);
    await userEvent.click(screen.getByRole("button", { name: "Check it" }));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    expect(inputs).toHaveLength(3);
    expect(inputs.map((i) => i.seed)).toEqual([inputs[0]?.seed, inputs[0]?.seed, inputs[0]?.seed]);
    expect(inputs[0]?.loras).toHaveLength(1);
    expect(inputs[1]?.loras).toHaveLength(1);
    expect(inputs[2]?.loras).toBeUndefined(); // the base model alone
    expect(calls.judge).toHaveBeenCalledTimes(3);
    expect(calls.saveEvaluation).toHaveBeenCalledWith(
      "m1",
      expect.arrayContaining([expect.objectContaining({ id: "s0-with_word", same: true })]),
    );
    expect(await screen.findByText("Judged 3.")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("still starts by itself when the screen mounts, unmounts and mounts again (strict mode)", async () => {
    const calls = api();
    render(
      <StrictMode>
        <CheckIt model={MODEL} api={calls} runs={runs([])} auto onSaved={() => {}} />
      </StrictMode>,
    );
    await waitFor(() => expect(calls.saveEvaluation).toHaveBeenCalled());
    expect(await screen.findByText("Judged 3.")).toBeInTheDocument();
  });

  it("starts by itself right after a run, once", async () => {
    const inputs: Input[] = [];
    const calls = api();
    const { rerender } = render(
      <CheckIt model={MODEL} api={calls} runs={runs(inputs)} auto onSaved={() => {}} />,
    );
    await waitFor(() => expect(calls.saveEvaluation).toHaveBeenCalledOnce());
    rerender(<CheckIt model={MODEL} api={calls} runs={runs(inputs)} auto onSaved={() => {}} />);
    expect(calls.checkPlan).toHaveBeenCalledOnce();
  });

  it("without a picture-reading model it still draws and leaves the verdict open", async () => {
    const inputs: Input[] = [];
    const calls = api({
      judge: vi.fn(async () => {
        throw new Error("Choose a model that can read pictures first (in the Model hub).");
      }),
    });
    render(<CheckIt model={MODEL} api={calls} runs={runs(inputs)} onSaved={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Check it" }));
    await waitFor(() => expect(calls.saveEvaluation).toHaveBeenCalled());
    expect(inputs).toHaveLength(3);
    expect(calls.judge).toHaveBeenCalledTimes(1); // after the first failure nothing more is asked
    expect(calls.saveEvaluation).toHaveBeenCalledWith(
      "m1",
      expect.arrayContaining([expect.objectContaining({ same: null })]),
    );
  });

  it("says in words when the check could not be made", async () => {
    const calls = api({
      checkPlan: vi.fn(async () => {
        throw new Error("Training could not be reached.");
      }),
    });
    render(<CheckIt model={MODEL} api={calls} runs={runs([])} onSaved={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Check it" }));
    expect(await screen.findByText("Training could not be reached.")).toBeInTheDocument();
  });

  it("offers nothing for a preview or a model the image engine does not have", () => {
    const { container } = render(
      <CheckIt
        model={{ ...MODEL, preview: true }}
        api={api()}
        runs={runs([])}
        onSaved={() => {}}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("the mark on a model", () => {
  it("says passed or did not pass with the sentence, and not checked yet before", () => {
    const m = (passed: boolean | null, note: string) =>
      ({ ...MODEL, card: { ...MODEL.card, evaluation: { passed, note } } }) as TrainedModel;
    const { rerender } = render(<EvaluationLine model={m(null, "Not evaluated yet.")} />);
    expect(screen.getByText("Not checked yet.")).toBeInTheDocument();
    rerender(<EvaluationLine model={m(true, "Looked like it 2 of 2.")} />);
    expect(screen.getByText("Passed")).toBeInTheDocument();
    rerender(<EvaluationLine model={m(false, "It did not pass: try more pictures.")} />);
    expect(screen.getByText("Did not pass")).toBeInTheDocument();
  });
});
