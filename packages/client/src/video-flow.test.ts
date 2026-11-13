import { describe, expect, it } from "vitest";
import type { ParsedEvent } from "./sse";
import {
  type VideoFlowState,
  initialVideoState,
  isVideoResting,
  videoFlowReducer,
} from "./video-flow";

const RUN = "11111111-1111-1111-1111-111111111111";
let seq = 0;
const ev = (event: string, data: Record<string, unknown>): ParsedEvent =>
  ({
    event,
    data: { run_id: RUN, thread_id: "t", seq: ++seq, ts: "", event, ...data },
  }) as ParsedEvent;
const play = (events: ParsedEvent[], from: VideoFlowState = initialVideoState) =>
  events.reduce((s, e) => videoFlowReducer(s, { type: "event", event: e }), from);
const started = (node: string) => ev("node", { node, status: "started", label: node });

describe("video flow", () => {
  it("moves from checking to making to done and keeps the clip", () => {
    let s = videoFlowReducer(initialVideoState, { type: "submitted" });
    expect(s.phase).toBe("checking");
    s = play([started("generate_video")], s);
    expect(s.phase).toBe("making");
    s = play([ev("job_progress", { capability: "video.generate", status: "queued" })], s);
    expect(s.job.status).toBe("queued");
    s = play(
      [ev("job_progress", { capability: "video.animate", status: "running", progress: 0.5 })],
      s,
    );
    expect(s.job).toEqual({ status: "running", progress: 0.5 });
    s = play([ev("job_progress", { capability: "image.generate", status: "running" })], s);
    expect(s.job.progress).toBe(0.5); // another capability's progress is not ours
    s = play(
      [
        ev("done", {
          outputs: {
            status: "done",
            video_id: "v1",
            video_url: "http://x/v.mp4",
            poster_url: "http://x/p.jpg",
            width: 768,
            height: 512,
            seconds: 2,
            prompt: "a fox",
            mode: "text",
          },
        }),
      ],
      s,
    );
    expect(s.phase).toBe("done");
    expect(s.result).toEqual({
      videoId: "v1",
      videoUrl: "http://x/v.mp4",
      posterUrl: "http://x/p.jpg",
      width: 768,
      height: 512,
      seconds: 2,
      prompt: "a fox",
      mode: "text",
    });
    expect(isVideoResting(s)).toBe(true);
    expect(s.lastSeq).toBeGreaterThan(0);
    expect(s.runId).toBe(RUN);
  });

  it("follows an extension and keeps the mode of the clip it made", () => {
    let s = videoFlowReducer(initialVideoState, { type: "submitted" });
    s = play([started("generate_video")], s);
    s = play(
      [ev("job_progress", { capability: "video.extend", status: "running", progress: 0.4 })],
      s,
    );
    expect(s.job).toEqual({ status: "running", progress: 0.4 });
    s = play([ev("done", { outputs: { status: "done", video_id: "v2", mode: "extend" } })], s);
    expect(s.phase).toBe("done");
    expect(s.result?.mode).toBe("extend");
  });

  it("shows a refusal in words and an error with whether to try again", () => {
    let s = play([
      ev("done", {
        outputs: { status: "refused", refusal: { code: "busy", message: "One at a time." } },
      }),
    ]);
    expect(s.phase).toBe("refused");
    expect(s.refusal).toEqual({ code: "busy", message: "One at a time." });
    s = play([ev("error", { code: "video_failed", message: "Nope.", retryable: true })]);
    expect(s.phase).toBe("error");
    expect(s.error).toEqual({ code: "video_failed", message: "Nope.", retryable: true });
  });

  it("restores, fails on the client and resets", () => {
    expect(videoFlowReducer(initialVideoState, { type: "restoring" }).label).toMatch(/left off/);
    const failed = videoFlowReducer(initialVideoState, { type: "failed", message: "Offline" });
    expect(failed.error).toEqual({ code: "client", message: "Offline", retryable: true });
    expect(videoFlowReducer(failed, { type: "reset" })).toEqual(initialVideoState);
    expect(isVideoResting(initialVideoState)).toBe(false);
  });
});
