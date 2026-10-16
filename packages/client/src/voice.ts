import type { ParsedEvent } from "./sse";
import { HttpError, type Transport, errorMessage } from "./transport";

export const VOICE_PRODUCT = "wasifyai-voice";

export type VoiceTask =
  | "speak"
  | "clone"
  | "design"
  | "edit"
  | "convert"
  | "music"
  | "separate"
  | "transcribe"
  | "lipsync";

/** `yes` and `conditional` may be used commercially; `no` and `unreviewed` are shown with a badge
 * and are never a default. */
export type CommercialUse = "yes" | "conditional" | "no" | "unreviewed";

/** Why a model cannot be used yet, and what to do: the dropdown's honest states (ADR-0066). */
export type ModelState = "ready" | "needs_runtime" | "can_install" | "not_available";

export type VoiceOption = {
  name: string;
  type: "bool" | "int" | "float" | "enum" | "string";
  label: string;
  description: string;
  default: unknown;
  min: number | null;
  max: number | null;
  values: string[];
};

export type VoiceInfo = { id: string; label: string; language: string; gender: string };

export type MusicMode = "song" | "sfx";

/** What a music model offers in one mode: whether it sings lyrics, whether it can leave the singing
 * out, and the lengths it makes, as [shortest, usual, longest] seconds. */
export type MusicModeRules = {
  lyrics?: "optional" | "required" | "unused";
  instrumental?: "toggle" | "always" | "never";
  duration: [number, number, number];
};

export type VoiceModelInfo = {
  id: string;
  title: string;
  licence: string;
  engine: string;
  family: string;
  tasks: VoiceTask[];
  recommended: VoiceTask[];
  languages: string[];
  sample_rate: number;
  commercial_use: CommercialUse;
  licence_evidence: string;
  reviewed: string;
  measured: {
    platform: string;
    speed_x: number | null;
    memory_gb: number | null;
    load_s: number | null;
  };
  voices: VoiceInfo[];
  default_voice: string | null;
  options: VoiceOption[];
  music: { modes?: Partial<Record<MusicMode, MusicModeRules>> };
  state: ModelState;
  files_ready: boolean;
  runtime_ready: boolean;
  bytes_missing: number;
};

export type RuntimePlan = {
  supported: boolean;
  platform: string;
  tag: string;
  bytes: number;
  url: string | null;
  backend: string | null;
  measured: boolean;
  found: { path: string; tag: string; backend: string } | null;
};

export type RuntimeInstall = {
  state: "idle" | "installing" | "ready" | "failed";
  step: string | null;
  message: string;
  done_bytes: number;
  total_bytes: number;
};

export type AudioRuntime = {
  installed: boolean;
  tag: string | null;
  backend: string | null;
  source: "managed" | "env" | "found" | null;
  running: boolean;
  plan: RuntimePlan;
  install: RuntimeInstall;
};

export type VoiceKind = "design" | "clone";
export type ConsentBasis = "own" | "permission";

/** A voice the person saved: described in words, or cloned from a recording. It works with any model
 * that can do that (the dropdown shows those), not with one model only. */
export type SavedVoice = {
  id: string;
  name: string;
  kind: VoiceKind;
  description: string;
  reference_text: string;
  reference_seconds: number | null;
  /** a link to play the recording of a cloned voice */
  reference_url?: string;
  consent: { basis?: ConsentBasis; statement?: string; accepted_at?: string };
  created_at: string;
  updated_at: string;
};

export type Track = {
  id: string;
  title: string;
  mode: MusicMode;
  description: string;
  lyrics: string;
  instrumental: boolean;
  model_id: string;
  options: Record<string, unknown>;
  seed: number | null;
  seconds: number;
  sample_rate: number;
  load_s: number;
  elapsed_s: number;
  created_at: string;
  updated_at: string;
  audio_url: string;
};

export type Speech = {
  id: string;
  mode: "speak" | "design" | "clone";
  saved_voice_id: string | null;
  text: string;
  model_id: string;
  voice: string | null;
  options: Record<string, unknown>;
  seconds: number;
  sample_rate: number;
  load_s: number;
  elapsed_s: number;
  created_at: string;
  audio_url: string;
};

export type TranscriptSegment = { start: number; end: number; text: string };

export type Transcript = {
  id: string;
  title: string;
  source_name: string;
  model_id: string;
  text: string;
  segments: TranscriptSegment[];
  seconds: number;
  elapsed_s: number;
  created_at: string;
  updated_at: string;
};

export type TranscriptFormat = "txt" | "srt" | "vtt";

export type VoiceApi = ReturnType<typeof createVoiceApi>;

const JSON_HEADERS = { "content-type": "application/json" };

export function createVoiceApi(transport: Transport) {
  const base = `/products/${VOICE_PRODUCT}`;
  async function request(path: string, init?: RequestInit): Promise<Response> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    return res;
  }
  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await request(path, init);
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }
  async function none(path: string, init?: RequestInit): Promise<void> {
    const res = await request(path, init);
    if (!res.ok && res.status !== 404) throw new HttpError(res.status, await errorMessage(res));
  }
  const post = (body: unknown): RequestInit => ({
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

  return {
    runtime: () => json<AudioRuntime>("/desktop/audio"),
    models: async (task?: VoiceTask) =>
      (
        await json<{ models: VoiceModelInfo[]; runtime: AudioRuntime }>(
          `/desktop/audio/models${task ? `?task=${task}` : ""}`,
        )
      ).models,
    installRuntime: (confirmBytes: number) =>
      json<AudioRuntime>("/desktop/audio/install", post({ confirm_bytes: confirmBytes })),
    useFoundRuntime: () => json<AudioRuntime>("/desktop/audio/use-found", { method: "POST" }),
    stopRuntime: () => json<{ stopped: boolean }>("/desktop/audio/stop", { method: "POST" }),

    speeches: async (limit = 100) =>
      (await json<{ items: Speech[] }>(`${base}/speeches?limit=${limit}`)).items,
    speech: (id: string) => json<Speech>(`${base}/speeches/${encodeURIComponent(id)}`),
    removeSpeech: (id: string) =>
      none(`${base}/speeches/${encodeURIComponent(id)}`, { method: "DELETE" }),
    /** The WAV as bytes, for saving (the audio link in `Speech` is for playing). */
    async downloadSpeech(id: string): Promise<Blob> {
      const res = await request(`${base}/speeches/${encodeURIComponent(id)}/download`);
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
      return res.blob();
    },

    tracks: async (limit = 100) =>
      (await json<{ items: Track[] }>(`${base}/tracks?limit=${limit}`)).items,
    renameTrack: (id: string, title: string) =>
      json<Track>(`${base}/tracks/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify({ title }),
      }),
    removeTrack: (id: string) =>
      none(`${base}/tracks/${encodeURIComponent(id)}`, { method: "DELETE" }),
    async downloadTrack(id: string): Promise<Blob> {
      const res = await request(`${base}/tracks/${encodeURIComponent(id)}/download`);
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
      return res.blob();
    },

    voices: async (kind?: VoiceKind) =>
      (await json<{ items: SavedVoice[] }>(`${base}/voices${kind ? `?kind=${kind}` : ""}`)).items,
    designVoice: (name: string, description: string) =>
      json<SavedVoice>(`${base}/voices/design`, post({ name, description })),
    cloneVoice(file: File, name: string, consent: ConsentBasis, referenceText?: string) {
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("name", name);
      form.append("consent", consent);
      if (referenceText) form.append("reference_text", referenceText);
      return json<SavedVoice>(`${base}/voices/clone`, { method: "POST", body: form });
    },
    updateVoice: (
      id: string,
      change: { name?: string; description?: string; reference_text?: string },
    ) =>
      json<SavedVoice>(`${base}/voices/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(change),
      }),
    removeVoice: (id: string) =>
      none(`${base}/voices/${encodeURIComponent(id)}`, { method: "DELETE" }),

    transcripts: async (limit = 100) =>
      (await json<{ items: Transcript[] }>(`${base}/transcripts?limit=${limit}`)).items,
    transcript: (id: string) => json<Transcript>(`${base}/transcripts/${encodeURIComponent(id)}`),
    transcribe(file: File, model?: string, title?: string) {
      const form = new FormData();
      form.append("file", file, file.name);
      if (model) form.append("model", model);
      if (title) form.append("title", title);
      return json<Transcript>(`${base}/transcripts`, { method: "POST", body: form });
    },
    renameTranscript: (id: string, title: string) =>
      json<Transcript>(`${base}/transcripts/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify({ title }),
      }),
    removeTranscript: (id: string) =>
      none(`${base}/transcripts/${encodeURIComponent(id)}`, { method: "DELETE" }),
    async exportTranscript(id: string, format: TranscriptFormat): Promise<Blob> {
      const res = await request(
        `${base}/transcripts/${encodeURIComponent(id)}/export?format=${format}`,
      );
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
      return res.blob();
    },
  };
}

export type SpeakRequest = {
  text: string;
  model?: string;
  /** a built-in voice of the chosen model */
  voice?: string;
  /** a voice the person saved (described or cloned) */
  savedVoice?: string;
  options?: Record<string, unknown>;
};

export type SpeakResult =
  | { ok: true; speech: Pick<Speech, "id" | "seconds" | "audio_url" | "sample_rate"> }
  | { ok: false; code: string; message: string };

/** Make one speech and follow the run to its end. The speech is saved by the engine, so the caller
 * reads the list again afterwards. */
export async function makeSpeech(
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  },
  request: SpeakRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<SpeakResult> {
  let result: SpeakResult = {
    ok: false,
    code: "lost",
    message:
      "We lost the connection while it was being made. It may still finish: look in the list.",
  };
  const input: Record<string, unknown> = { text: request.text };
  if (request.model) input.model = request.model;
  if (request.voice) input.voice = request.voice;
  if (request.savedVoice) input.saved_voice = request.savedVoice;
  if (request.options && Object.keys(request.options).length) input.options = request.options;
  await runs.startRun(VOICE_PRODUCT, input, signal, (e) => {
    const data = e.data as unknown as Record<string, unknown>;
    if (e.event === "node" && typeof data.label === "string") onStep?.(data.label);
    if (e.event === "error") {
      result = {
        ok: false,
        code: String(data.code ?? "failed"),
        message: String(data.message ?? "Something went wrong."),
      };
    }
    if (e.event === "done") {
      const out = (data.outputs as Record<string, unknown>) ?? {};
      if (out.status === "refused") {
        const refusal = (out.refusal as Record<string, string>) ?? {};
        result = {
          ok: false,
          code: refusal.code ?? "refused",
          message: refusal.message ?? "That could not be made.",
        };
      } else if (typeof out.speech_id === "string") {
        result = {
          ok: true,
          speech: {
            id: out.speech_id,
            seconds: Number(out.seconds ?? 0),
            audio_url: String(out.audio_url ?? ""),
            sample_rate: Number(out.sample_rate ?? 0),
          },
        };
      }
    }
  });
  return result;
}

export type MusicRequest = {
  description: string;
  model?: string;
  mode?: MusicMode;
  lyrics?: string;
  instrumental?: boolean;
  /** seconds; the model's usual length when left out */
  duration?: number;
  seed?: number;
  title?: string;
  /** the model's own options (its descriptor lists them) */
  options?: Record<string, unknown>;
};

export type MusicResult =
  | { ok: true; track: Pick<Track, "id" | "title" | "seconds" | "audio_url"> }
  | { ok: false; code: string; message: string };

/** Make one piece of music and follow the run to its end. It can take minutes; the track is saved by
 * the engine, so the caller reads the list again afterwards. */
export async function makeTrack(
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  },
  request: MusicRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<MusicResult> {
  let result: MusicResult = {
    ok: false,
    code: "lost",
    message:
      "We lost the connection while it was being made. It may still finish: look in the list.",
  };
  const input: Record<string, unknown> = { task: "music", text: request.description };
  if (request.model) input.model = request.model;
  if (request.mode) input.music_mode = request.mode;
  if (request.lyrics?.trim()) input.lyrics = request.lyrics;
  if (request.instrumental) input.instrumental = true;
  if (request.duration !== undefined) input.duration = request.duration;
  if (request.seed !== undefined) input.seed = request.seed;
  if (request.title?.trim()) input.title = request.title;
  if (request.options && Object.keys(request.options).length) input.options = request.options;
  await runs.startRun(VOICE_PRODUCT, input, signal, (e) => {
    const data = e.data as unknown as Record<string, unknown>;
    if (e.event === "node" && typeof data.label === "string") onStep?.(data.label);
    if (e.event === "error") {
      result = {
        ok: false,
        code: String(data.code ?? "failed"),
        message: String(data.message ?? "Something went wrong."),
      };
    }
    if (e.event === "done") {
      const out = (data.outputs as Record<string, unknown>) ?? {};
      if (out.status === "refused") {
        const refusal = (out.refusal as Record<string, string>) ?? {};
        result = {
          ok: false,
          code: refusal.code ?? "refused",
          message: refusal.message ?? "That could not be made.",
        };
      } else if (typeof out.track_id === "string") {
        result = {
          ok: true,
          track: {
            id: out.track_id,
            title: String(out.title ?? ""),
            seconds: Number(out.seconds ?? 0),
            audio_url: String(out.audio_url ?? ""),
          },
        };
      }
    }
  });
  return result;
}
