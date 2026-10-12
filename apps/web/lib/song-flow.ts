// Turns the server's event stream into UI state. Pure: no fetch, no React, so it is tested
// against recorded event sequences. See products/wasifyai-music/README.md for the contract.
import type { ParsedEvent } from "./sse";

export type Phase =
  | "idle"
  | "checking" // request sent, guardrail running
  | "writing" // lyrics streaming in
  | "approving" // waiting for the user's decision
  | "answering" // the user answered, waiting for the server
  | "generating" // music and cover jobs
  | "done"
  | "refused"
  | "error";

export type Step = "check" | "lyrics" | "approve" | "music" | "cover";
export type JobStatus = "waiting" | "queued" | "running" | "completed" | "failed";
export type Job = { status: JobStatus; position?: number; progress?: number };

export type Draft = {
  title: string;
  lyrics: string;
  style: string;
  regenerationsLeft: number;
};

export type SongResult = {
  songId: string;
  title: string;
  lyrics: string;
  style: string;
  audioUrl: string;
  coverUrl: string | null;
};

export type FlowError = { code: string; message: string; retryable: boolean };

export type FlowState = {
  phase: Phase;
  step: Step;
  label: string;
  runId?: string;
  lastSeq: number;
  lyrics: string; // streamed so far
  draft?: Draft;
  approvalError?: string;
  music: Job;
  cover: Job;
  result?: SongResult;
  refusal?: { code: string; message: string };
  error?: FlowError;
};

export const initialState: FlowState = {
  phase: "idle",
  step: "check",
  label: "",
  lastSeq: 0,
  lyrics: "",
  music: { status: "waiting" },
  cover: { status: "waiting" },
};

export type FlowAction =
  | { type: "event"; event: ParsedEvent }
  | { type: "submitted" }
  | { type: "restoring" }
  | { type: "answered" }
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
    case "node": {
      if (d.status !== "started") return state;
      const label = str(d.label, state.label);
      switch (d.node) {
        case "check_request":
          return { ...state, phase: "checking", step: "check", label };
        case "write_lyrics":
          // Every start clears the lyrics: a repeat means the draft is being rewritten.
          return {
            ...state,
            phase: "writing",
            step: "lyrics",
            label,
            lyrics: "",
            draft: undefined,
            approvalError: undefined,
          };
        case "generate_music":
          return { ...state, phase: "generating", step: "music", label };
        case "screen_cover": // the music is done; the cover step begins with its safety check
        case "generate_cover":
          return { ...state, phase: "generating", step: "cover", label };
        default:
          return state;
      }
    }
    case "token":
      return d.node === "write_lyrics" ? { ...state, lyrics: state.lyrics + str(d.text) } : state;
    case "interrupt": {
      if (d.kind !== "approve_lyrics") return state;
      const p = (d.payload ?? {}) as Data;
      const draft: Draft = {
        title: str(p.title),
        lyrics: str(p.lyrics),
        style: str(p.style),
        regenerationsLeft: num(p.regenerations_left) ?? 0,
      };
      return {
        ...state,
        phase: "approving",
        step: "approve",
        label: "Review your lyrics",
        lyrics: draft.lyrics,
        draft,
        approvalError: str(p.error) || undefined,
      };
    }
    case "job_progress": {
      const key =
        d.capability === "music.generate"
          ? "music"
          : d.capability === "image.generate"
            ? "cover"
            : null;
      return key ? { ...state, [key]: jobUpdate(state[key], d) } : state;
    }
    case "done": {
      const out = (d.outputs ?? {}) as Data;
      if (out.status === "refused") {
        const r = (out.refusal ?? {}) as Data;
        return {
          ...state,
          phase: "refused",
          refusal: {
            code: str(r.code, "refused"),
            message: str(r.message, "That request can't be made into a song."),
          },
        };
      }
      return {
        ...state,
        phase: "done",
        label: "Your song is ready",
        result: {
          songId: str(out.song_id),
          title: str(out.title),
          lyrics: str(out.lyrics),
          style: str(out.style),
          audioUrl: str(out.audio_url),
          coverUrl: str(out.cover_url) || null,
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
      return { ...initialState, phase: "checking", label: "Sending your idea" };
    case "restoring":
      return { ...initialState, phase: "checking", label: "Picking up where you left off" };
    case "answered":
      return {
        ...state,
        phase: "answering",
        label: "Checking your choice",
        approvalError: undefined,
      };
    case "failed":
      return {
        ...state,
        phase: "error",
        error: { code: "client", message: action.message, retryable: action.retryable ?? true },
      };
    case "reset":
      return initialState;
    case "event": {
      const d = action.event.data as unknown as Data;
      const next = applyEvent(state, action.event.event, d);
      const seq = num(d.seq) ?? 0;
      return {
        ...next,
        runId: next.runId ?? (typeof d.run_id === "string" ? d.run_id : undefined),
        lastSeq: Math.max(next.lastSeq, seq),
      };
    }
  }
}

/** Is the run at a point where the stream is expected to be closed (nothing more is coming)? */
export function isResting(state: FlowState): boolean {
  return ["idle", "approving", "done", "refused", "error"].includes(state.phase);
}

export const STEPS: { id: Step; label: string }[] = [
  { id: "check", label: "Check request" },
  { id: "lyrics", label: "Write lyrics" },
  { id: "approve", label: "Your approval" },
  { id: "music", label: "Make music" },
  { id: "cover", label: "Paint cover" },
];

export type StepView = { id: Step; label: string; status: "done" | "active" | "todo" | "failed" };

export function stepViews(state: FlowState): StepView[] {
  const current = STEPS.findIndex((s) => s.id === state.step);
  return STEPS.map((s, i) => {
    let status: StepView["status"] = i < current ? "done" : i === current ? "active" : "todo";
    if (state.phase === "done") status = "done";
    if (state.phase === "idle") status = "todo";
    if (i === current && (state.phase === "error" || state.phase === "refused")) status = "failed";
    if (state.phase === "approving" && i === current) status = "active";
    return { ...s, status };
  });
}
