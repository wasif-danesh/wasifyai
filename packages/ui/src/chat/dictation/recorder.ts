// Recording the microphone in the page (ADR-0083, decision 5). The browser's own speech recognition is not used: it sends sound to
// a third party and does not work offline. The sound stays in this page until it is sent, once, to our own engine.
import { encodeWav, peakOf, toSpeechRate } from "./wav";

/** Where the recorder's worklet is served from: a file of the app itself (the desktop window refuses a blob). */
export const WORKLET_URL = "/recorder-worklet.js";
/** A clip is stopped here: the engine takes five minutes at most. */
export const MAX_RECORD_SECONDS = 290;

export type MicProblem = "permission" | "no_microphone" | "busy" | "unsupported" | "failed";

/** A failure with the plain sentence to show. */
export class MicError extends Error {
  constructor(
    readonly problem: MicProblem,
    message: string,
  ) {
    super(message);
  }
}

/** A clip being recorded. `stop` ends it and gives the WAV; `cancel` throws it away. Both release the microphone. */
export type Recording = {
  /** the name of the microphone that is listening (the operating system's name for it) */
  label: string;
  stop(): Promise<{ wav: Blob; seconds: number; peak: number }>;
  cancel(): void;
};

export type Recorder = () => Promise<Recording>;

/** The sentence for a failure to open the microphone: no jargon, and what to do. */
export function micProblem(e: unknown): MicError {
  if (e instanceof MicError) return e;
  const name = e instanceof DOMException || e instanceof Error ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError")
    return new MicError(
      "permission",
      "The microphone is turned off for this app. Allow it in your computer's privacy settings, then try again.",
    );
  if (
    name === "NotFoundError" ||
    name === "OverconstrainedError" ||
    name === "DevicesNotFoundError"
  )
    return new MicError(
      "no_microphone",
      "No microphone was found. Plug one in or choose one in your computer's sound settings, then try again.",
    );
  if (name === "NotReadableError" || name === "AbortError" || name === "TrackStartError")
    return new MicError(
      "busy",
      "The microphone is being used by another app. Close it there, then try again.",
    );
  return new MicError("failed", "The microphone could not be started. Try again.");
}

/** Start listening. Rejects with a `MicError` whose message is fit to show. */
export const startRecording: Recorder = async () => {
  const media = typeof navigator === "undefined" ? undefined : navigator.mediaDevices;
  const Context =
    typeof window === "undefined"
      ? undefined
      : (window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext);
  if (!media?.getUserMedia || !Context || typeof AudioWorkletNode === "undefined")
    throw new MicError("unsupported", "This window cannot use a microphone.");

  let stream: MediaStream;
  try {
    stream = await media.getUserMedia({ audio: { channelCount: 1 } });
  } catch (e) {
    throw micProblem(e);
  }
  const release = () => {
    for (const t of stream.getTracks()) t.stop();
  };
  let ctx: AudioContext | undefined;
  try {
    ctx = new Context();
    await ctx.resume();
    try {
      await ctx.audioWorklet.addModule(WORKLET_URL);
    } catch {
      throw new MicError(
        "failed",
        "The recorder could not be loaded. Restart the app and try again.",
      );
    }
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, "wasifyai-recorder", {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
      channelCountMode: "explicit",
    });
    const blocks: Float32Array[] = [];
    let flushed: (() => void) | null = null;
    node.port.onmessage = (e: MessageEvent) => {
      if (e.data === "flushed") flushed?.();
      else if (e.data instanceof Float32Array) blocks.push(e.data);
    };
    source.connect(node);
    const rate = ctx.sampleRate;
    const label = stream.getAudioTracks()[0]?.label ?? "";
    const context = ctx;
    const close = () => {
      source.disconnect();
      node.disconnect();
      release();
      void context.close().catch(() => {});
    };
    return {
      label,
      async stop() {
        const done = new Promise<void>((resolve) => {
          flushed = resolve;
          setTimeout(resolve, 500); // the worklet did not answer: use what came
        });
        node.port.postMessage("flush");
        await done;
        close();
        const samples = toSpeechRate(blocks, rate);
        return { wav: encodeWav(samples), seconds: samples.length / 16000, peak: peakOf(samples) };
      },
      cancel: close,
    };
  } catch (e) {
    release();
    if (ctx) void ctx.close().catch(() => {});
    throw micProblem(e);
  }
};
