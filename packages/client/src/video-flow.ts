// Turns the video run's event stream into UI state. Pure: no fetch, no React, so it is tested against
// recorded event sequences. See products/wasifyai-video/README.md for the contract.
import type { FlowError, Job, Mode } from "./image-flow";
import type { ParsedEvent } from "./sse";

/**
 * How a clip was made: from words, from a picture, by carrying on another clip (Extend video), or it is a
 * video file the person added from their computer.
 */
export type VideoMode = Mode | "extend" | "import";

export type VideoPhase =
  | "idle"
  | "checking" // request sent, guardrail running
  | "making" // the clip is being made: it will be in Your videos when it is done
  | "done"
  | "refused"
  | "error";

export type VideoResult = {
  videoId: string;
  videoUrl: string;
  posterUrl: string;
  width: number;
  height: number;
  seconds: number;
  prompt: string;
  mode: VideoMode;
};

export type VideoFlowState = {
  phase: VideoPhase;
  label: string;
  runId?: string;
  lastSeq: number;
  job: Job;
  result?: VideoResult;
  refusal?: { code: string; message: string };
  error?: FlowError;
};

export const initialVideoState: VideoFlowState = {
  phase: "idle",
  label: "",
  lastSeq: 0,
  job: { status: "waiting" },
};

export type VideoFlowAction =
  | { type: "event"; event: ParsedEvent }
  | { type: "submitted" }
  | { type: "restoring" }
  | { type: "failed"; message: string; retryable?: boolean }
  | { type: "reset" };

type Data = Record<string, unknown>;
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const num = (v: unknown): number | undefined => (typeof v === "number" ? v : undefined);

function jobUpdate(job: Job, d: Data): Job {
  switch (d.status) {
    case "queued":
      return { status: "queued", position: num(d.queue_position) };
    case "running":
      return { status: "running", progress: num(d.progress) ?? job.progress ?? 0 };
    case "completed":
      return { status: "completed", progress: 1 };
    case "failed":
      return { status: "failed", progress: job.progress };
    default:
      return job;
  }
}

function applyEvent(state: VideoFlowState, name: string, d: Data): VideoFlowState {
  switch (name) {
    case "node":
      if (d.status !== "started") return state;
      if (d.node === "check_request") {
        return { ...state, phase: "checking", label: str(d.label, state.label) };
      }
      if (d.node === "generate_video") {
        return { ...state, phase: "making", label: str(d.label, state.label) };
      }
      return state;
    case "job_progress":
      return d.capability === "video.generate" ||
        d.capability === "video.animate" ||
        d.capability === "video.extend"
        ? { ...state, job: jobUpdate(state.job, d) }
        : state;
    case "done": {
      const out = (d.outputs ?? {}) as Data;
      if (out.status === "refused") {
        const r = (out.refusal ?? {}) as Data;
        return {
          ...state,
          phase: "refused",
          refusal: {
            code: str(r.code, "refused"),
            message: str(r.message, "That request can't be made into a video."),
          },
        };
      }
      return {
        ...state,
        phase: "done",
        label: "Your video is ready",
        result: {
          videoId: str(out.video_id),
          videoUrl: str(out.video_url),
          posterUrl: str(out.poster_url),
          width: num(out.width) ?? 0,
          height: num(out.height) ?? 0,
          seconds: num(out.seconds) ?? 0,
          prompt: str(out.prompt),
          mode:
            out.mode === "image" || out.mode === "extend" || out.mode === "import"
              ? out.mode
              : "text",
        },
      };
    }
    case "error":
      return {
        ...state,
        phase: "error",
        error: {
          code: str(d.code, "error"),
          message: str(d.message, "Something went wrong."),
          retryable: d.retryable === true,
        },
      };
    default:
      return state;
  }
}

export function videoFlowReducer(state: VideoFlowState, action: VideoFlowAction): VideoFlowState {
  switch (action.type) {
    case "submitted":
      return { ...initialVideoState, phase: "checking", label: "Checking your request" };
    case "restoring":
      return { ...initialVideoState, phase: "checking", label: "Picking up where you left off" };
    case "failed":
      return {
        ...state,
        phase: "error",
        error: { code: "client", message: action.message, retryable: action.retryable ?? true },
      };
    case "reset":
      return initialVideoState;
    case "event": {
      const { event } = action;
      const data = event.data as Data;
      const next = applyEvent(state, event.event, data);
      const seq = num(data.seq);
      return {
        ...next,
        runId: str(data.run_id) || next.runId,
        lastSeq: seq !== undefined && seq > next.lastSeq ? seq : next.lastSeq,
      };
    }
  }
}

/** True once there is nothing more to wait for: no reconnecting needed. */
export function isVideoResting(state: VideoFlowState): boolean {
  return state.phase === "done" || state.phase === "refused" || state.phase === "error";
}
