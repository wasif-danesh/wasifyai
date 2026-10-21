// Turns the image run's event stream into UI state. Pure: no fetch, no React, so it is tested against
// recorded event sequences. See products/wasifyai-image/README.md for the contract.
import type { ParsedEvent } from "./sse";

export type Mode = "text" | "image";

/**
 * What an image was made by: from words, an edit of a picture, a new picture from two (`reference`), or a
 * change of a painted area (`inpaint`). Video has the first two only (`Mode`).
 */
export type ImageMode = Mode | "reference" | "inpaint";
const IMAGE_MODES: readonly ImageMode[] = ["text", "image", "reference", "inpaint"];
const modeOf = (v: unknown): ImageMode => IMAGE_MODES.find((m) => m === v) ?? "text";

export type Phase =
  | "idle"
  | "checking" // request sent, guardrail running
  | "working" // the image is being made
  | "done"
  | "refused"
  | "error";

export type JobStatus = "waiting" | "queued" | "running" | "completed" | "failed";
export type Job = { status: JobStatus; position?: number; progress?: number };

export type ImageResult = {
  imageId: string;
  imageUrl: string;
  thumbUrl: string;
  width: number;
  height: number;
  prompt: string;
  mode: ImageMode;
};

export type FlowError = { code: string; message: string; retryable: boolean };

export type FlowState = {
  phase: Phase;
  label: string;
  runId?: string;
  lastSeq: number;
  job: Job;
  result?: ImageResult;
  refusal?: { code: string; message: string };
  error?: FlowError;
};

export const initialState: FlowState = {
  phase: "idle",
  label: "",
  lastSeq: 0,
  job: { status: "waiting" },
};

export type FlowAction =
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

function applyEvent(state: FlowState, name: string, d: Data): FlowState {
  switch (name) {
    case "node":
      if (d.status !== "started") return state;
      if (d.node === "check_request") {
        return { ...state, phase: "checking", label: str(d.label, state.label) };
      }
      if (d.node === "generate_image") {
        return { ...state, phase: "working", label: str(d.label, state.label) };
      }
      return state;
    case "job_progress":
      return d.capability === "image.generate" || d.capability === "image.edit"
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
            message: str(r.message, "That request can't be made into an image."),
          },
        };
      }
      return {
        ...state,
        phase: "done",
        label: "Your image is ready",
        result: {
          imageId: str(out.image_id),
          imageUrl: str(out.image_url),
          thumbUrl: str(out.thumb_url),
          width: num(out.width) ?? 0,
          height: num(out.height) ?? 0,
          prompt: str(out.prompt),
          mode: modeOf(out.mode),
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

export function flowReducer(state: FlowState, action: FlowAction): FlowState {
  switch (action.type) {
    case "submitted":
      return { ...initialState, phase: "checking", label: "Checking your request" };
    case "restoring":
      return { ...initialState, phase: "checking", label: "Picking up where you left off" };
    case "failed":
      return {
        ...state,
        phase: "error",
        error: {
          code: "client",
          message: action.message,
          retryable: action.retryable ?? true,
        },
      };
    case "reset":
      return initialState;
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
export function isResting(state: FlowState): boolean {
  return state.phase === "done" || state.phase === "refused" || state.phase === "error";
}
