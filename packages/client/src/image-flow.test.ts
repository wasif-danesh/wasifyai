import { describe, expect, it } from "vitest";
import { type FlowState, flowReducer, initialState, isResting } from "./image-flow";
import type { ParsedEvent } from "./sse";

const RUN = "11111111-1111-1111-1111-111111111111";
let seq = 0;
const ev = (event: string, data: Record<string, unknown>): ParsedEvent =>
  ({
    event,
    data: { run_id: RUN, thread_id: "t", seq: ++seq, ts: "", event, ...data },
  }) as ParsedEvent;
const play = (events: ParsedEvent[], from: FlowState = initialState) =>
  events.reduce((s, e) => flowReducer(s, { type: "event", event: e }), from);
const started = (node: string) => ev("node", { node, status: "started", label: node });

describe("image flow", () => {
  it("moves from checking to working to done", () => {
    let s = flowReducer(initialState, { type: "submitted" });
    expect(s.phase).toBe("checking");
    s = play([started("check_request")], s);
    expect(s.phase).toBe("checking");
    s = play([started("generate_image")], s);
    expect(s.phase).toBe("working");
    s = play(
      [ev("job_progress", { capability: "image.edit", status: "queued", queue_position: 2 })],
      s,
    );
    expect(s.job).toEqual({ status: "queued", position: 2 });
    s = play(
      [ev("job_progress", { capability: "image.edit", status: "running", progress: 0.4 })],
      s,
    );
    expect(s.job).toEqual({ status: "running", progress: 0.4 });
    s = play(
      [
        ev("done", {
          outputs: {
            status: "done",
            image_id: "i1",
            image_url: "http://x/i.png",
            thumb_url: "http://x/t.jpg",
            width: 1024,
            height: 768,
            prompt: "a cat",
            mode: "image",
          },
        }),
      ],
      s,
    );
    expect(s.phase).toBe("done");
    expect(s.result).toEqual({
      imageId: "i1",
      imageUrl: "http://x/i.png",
      thumbUrl: "http://x/t.jpg",
      width: 1024,
      height: 768,
      prompt: "a cat",
      mode: "image",
    });
    expect(isResting(s)).toBe(true);
  });

  it("ignores progress from other capabilities", () => {
    const s = play([ev("job_progress", { capability: "music.generate", status: "running" })]);
    expect(s.job.status).toBe("waiting");
  });

  it("shows a refusal with its message", () => {
    const s = play([
      ev("done", { outputs: { status: "refused", refusal: { code: "minors", message: "No." } } }),
    ]);
    expect(s.phase).toBe("refused");
    expect(s.refusal).toEqual({ code: "minors", message: "No." });
  });

  it("records errors and tracks the last sequence number", () => {
    const s = play([ev("error", { code: "boom", message: "Bad", retryable: true })]);
    expect(s.phase).toBe("error");
    expect(s.error).toEqual({ code: "boom", message: "Bad", retryable: true });
    expect(s.runId).toBe(RUN);
    expect(s.lastSeq).toBeGreaterThan(0);
  });

  it("fails and resets from the client side", () => {
    const failed = flowReducer(initialState, { type: "failed", message: "no" });
    expect(failed.error).toEqual({ code: "client", message: "no", retryable: true });
    expect(flowReducer(failed, { type: "reset" })).toEqual(initialState);
  });
});
