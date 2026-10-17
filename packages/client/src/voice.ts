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
export type EditAction = "repaint" | "extend" | "cover" | "inpaint" | "restyle";

/** What a music model offers in one mode: whether it sings lyrics, whether it can leave the singing
 * out, and the lengths it makes, as [shortest, usual, longest] seconds. */
export type MusicModeRules = {
  lyrics?: "optional" | "required" | "unused";
  instrumental?: "toggle" | "always" | "never";
  duration: [number, number, number];
};

/** What a model can do to a clip: the actions, how many parts at once, how long a clip. */
export type MusicEditRules = { actions: EditAction[]; max_ranges: number; max_source_s: number };

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
  music: { modes?: Partial<Record<MusicMode, MusicModeRules>> & { edit?: MusicEditRules } };
  /** the stems a separator returns (in this order) and the longest recording it takes */
  separate?: { stems?: string[]; max_source_s?: number };
  convert?: { reference_seconds?: [number, number]; max_source_s?: number };
  speech_edit?: { max_changes?: number; max_source_s?: number };
  lipsync?: { max_voice_s?: number; max_side?: number; fps?: number; mark?: string };
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

/** The lip sync engine (MuseTalk): an optional component, set up on a click after its size is shown. */
export type LipSyncEngine = {
  installed: boolean;
  source: "managed" | "env" | null;
  running: boolean;
  plan: { supported: boolean; platform: string; commit: string; bytes: number; uv: boolean };
  install: RuntimeInstall;
};

export type PictureBasis = "drawn" | "own" | "permission";
export type VoiceBasis = "generated" | "own" | "permission";

/** A talking video made here. The picture and the voice basis are what the person said about them. */
export type Clip = {
  id: string;
  title: string;
  model_id: string;
  script: string;
  voice: { kind?: "track" | "speech"; id?: string };
  seconds: number;
  fps: number;
  width: number;
  height: number;
  consent: {
    picture?: PictureBasis;
    voice?: VoiceBasis;
    mark?: string;
    accepted_at?: string;
    picture_statement?: string;
    voice_statement?: string;
  };
  favourite: boolean;
  load_s: number;
  elapsed_s: number;
  created_at: string;
  updated_at: string;
  video_url: string;
  picture_url: string;
};

export type AddedPicture = { id: string; width: number; height: number; url: string };

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

/** What a track is: music made here, a change to music, or what an audio tool made or was given. */
export type TrackMode =
  | MusicMode
  | "edit"
  | "stem"
  | "converted"
  | "edited"
  | "imported"
  | "dubbed"
  | "chapter"
  | "audiobook";

export type Track = {
  id: string;
  title: string;
  mode: TrackMode;
  favourite: boolean;
  /** the track this was made from, when it is an edit */
  parent_id: string | null;
  edit: {
    action?: EditAction | "separate" | "convert" | "speech_edit" | "import" | "dub" | "audiobook";
    book?: string;
    chapter?: number;
    of?: number;
    language?: string;
    ranges?: [number, number][];
    strength?: number | null;
    extend_s?: number | null;
    stem?: string;
    voice?: string;
    old_text?: string;
    new_text?: string;
    file?: string;
  };
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

    tracks: async (opts: { limit?: number; favourites?: boolean } = {}) =>
      (
        await json<{ items: Track[] }>(
          `${base}/tracks?limit=${opts.limit ?? 100}${opts.favourites ? "&favourites=true" : ""}`,
        )
      ).items,
    track: (id: string) => json<Track>(`${base}/tracks/${encodeURIComponent(id)}`),
    updateTrack: (id: string, change: { title?: string; favourite?: boolean }) =>
      json<Track>(`${base}/tracks/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(change),
      }),
    renameTrack: (id: string, title: string) =>
      json<Track>(`${base}/tracks/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify({ title }),
      }),
    /** The formats a track can be saved in on this computer: WAV always, MP3 and M4A where a tool is. */
    formats: async () => (await json<{ formats: string[] }>(`${base}/formats`)).formats,
    removeTrack: (id: string) =>
      none(`${base}/tracks/${encodeURIComponent(id)}`, { method: "DELETE" }),
    async downloadTrack(id: string, format: "wav" | "mp3" | "m4a" = "wav"): Promise<Blob> {
      const res = await request(
        `${base}/tracks/${encodeURIComponent(id)}/download?format=${format}`,
      );
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
      return res.blob();
    },

    /** Add a recording from this computer to Your music, so the audio tools can work on it. */
    importTrack(file: File, title?: string) {
      const form = new FormData();
      form.append("file", file, file.name);
      if (title) form.append("title", title);
      return json<Track>(`${base}/tracks/import`, { method: "POST", body: form });
    },
    /** What a recording of the library says, written down. Nothing is saved. */
    /** The chapters of a long text, to read and change before anything is spoken. Nothing is kept. */
    planBook: (text: string, target?: number) =>
      json<{ chapters: BookChapter[]; chars: number; estimated_seconds: number }>(
        `${base}/audiobook/plan`,
        post({ text, ...(target ? { target } : {}) }),
      ),
    words: (source: AudioSource, model?: string) =>
      json<{ text: string; seconds: number; model: string }>(
        `${base}/words`,
        post({ ...source, model }),
      ),

    lipsyncEngine: () => json<LipSyncEngine>("/desktop/lipsync"),
    installLipsyncEngine: (confirmBytes: number) =>
      json<LipSyncEngine>("/desktop/lipsync/install", post({ confirm_bytes: confirmBytes })),
    stopLipsyncEngine: () =>
      json<{ stopped: boolean }>("/desktop/lipsync/stop", { method: "POST" }),
    /** A picture to make a talking video from; it is kept until a clip uses it, or for a day. */
    addPicture(file: File) {
      const form = new FormData();
      form.append("file", file, file.name);
      return json<AddedPicture>(`${base}/pictures`, { method: "POST", body: form });
    },
    clips: async (limit = 100) =>
      (await json<{ items: Clip[] }>(`${base}/clips?limit=${limit}`)).items,
    clip: (id: string) => json<Clip>(`${base}/clips/${encodeURIComponent(id)}`),
    updateClip: (id: string, change: { title?: string; favourite?: boolean }) =>
      json<Clip>(`${base}/clips/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(change),
      }),
    removeClip: (id: string) =>
      none(`${base}/clips/${encodeURIComponent(id)}`, { method: "DELETE" }),
    async downloadClip(id: string): Promise<Blob> {
      const res = await request(`${base}/clips/${encodeURIComponent(id)}/download`);
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

/** A chapter of a book: its title and its words, with the size the engine counted. */
export type BookChapter = { title: string; text: string; chars: number; estimated_seconds: number };

/** A recording of the library an audio tool works on. */
export type AudioSource = { kind: "track" | "speech"; id: string };

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
export function makeTrack(
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  },
  request: MusicRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<MusicResult> {
  const input: Record<string, unknown> = { task: "music", text: request.description };
  if (request.model) input.model = request.model;
  if (request.mode) input.music_mode = request.mode;
  if (request.lyrics?.trim()) input.lyrics = request.lyrics;
  if (request.instrumental) input.instrumental = true;
  if (request.duration !== undefined) input.duration = request.duration;
  if (request.seed !== undefined) input.seed = request.seed;
  if (request.title?.trim()) input.title = request.title;
  if (request.options && Object.keys(request.options).length) input.options = request.options;
  return followMusic(runs, input, signal, onStep);
}

async function followMusic(
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  },
  input: Record<string, unknown>,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<MusicResult> {
  let result: MusicResult = {
    ok: false,
    code: "lost",
    message:
      "We lost the connection while it was being made. It may still finish: look in the list.",
  };
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

export type EditRequest = {
  /** the track to change */
  source: string;
  action: EditAction;
  description: string;
  model?: string;
  /** parts of the clip, as [start, end] seconds */
  ranges?: [number, number][];
  strength?: number;
  extend?: number;
  seed?: number;
  title?: string;
  options?: Record<string, unknown>;
};

/** Change a track and follow the run to its end; the result is a new track that remembers its source. */
export function makeEdit(
  runs: Parameters<typeof makeTrack>[0],
  request: EditRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<MusicResult> {
  const input: Record<string, unknown> = {
    task: "music_edit",
    source_track: request.source,
    edit_action: request.action,
    text: request.description,
  };
  if (request.model) input.model = request.model;
  if (request.ranges?.length) input.edit_ranges = request.ranges;
  if (request.strength !== undefined) input.strength = request.strength;
  if (request.extend !== undefined) input.extend_s = request.extend;
  if (request.seed !== undefined) input.seed = request.seed;
  if (request.title?.trim()) input.title = request.title;
  if (request.options && Object.keys(request.options).length) input.options = request.options;
  return followMusic(runs, input, signal, onStep);
}

export type LyricsRequest = {
  idea: string;
  style?: string;
  /** the length of the music, which sets how many lines are written */
  duration?: number;
  language?: string;
};

export type LyricsResult =
  | { ok: true; lyrics: string }
  | { ok: false; code: string; message: string };

/** Ask the chat model for lyrics. `onText` gets the words as they arrive. */
export async function makeLyrics(
  runs: Parameters<typeof makeTrack>[0],
  request: LyricsRequest,
  signal: AbortSignal,
  onText?: (soFar: string) => void,
): Promise<LyricsResult> {
  let result: LyricsResult = {
    ok: false,
    code: "lost",
    message: "We lost the connection while the words were being written.",
  };
  let streamed = "";
  const input: Record<string, unknown> = { task: "lyrics", text: request.idea };
  if (request.style) input.style = request.style;
  if (request.duration !== undefined) input.duration = request.duration;
  if (request.language) input.language = request.language;
  await runs.startRun(VOICE_PRODUCT, input, signal, (e) => {
    const data = e.data as unknown as Record<string, unknown>;
    if (e.event === "token" && typeof data.text === "string") {
      streamed += data.text;
      onText?.(streamed);
    }
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
          message: refusal.message ?? "That could not be written.",
        };
      } else if (typeof out.lyrics === "string") {
        result = { ok: true, lyrics: out.lyrics };
      }
    }
  });
  return result;
}

export type ToolTrack = Pick<Track, "id" | "title" | "seconds" | "audio_url"> & { stem?: string };

export type ToolResult =
  | { ok: true; tracks: ToolTrack[] }
  | { ok: false; code: string; message: string };

type Runs = Parameters<typeof makeTrack>[0];

function sourceInput(source: AudioSource): Record<string, unknown> {
  return source.kind === "track" ? { source_track: source.id } : { source_speech: source.id };
}

async function followTool(
  runs: Runs,
  input: Record<string, unknown>,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<ToolResult> {
  let result: ToolResult = {
    ok: false,
    code: "lost",
    message:
      "We lost the connection while it was being made. It may still finish: look in Your music.",
  };
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
          message: refusal.message ?? "That could not be done.",
        };
      } else if (Array.isArray(out.tracks)) {
        result = {
          ok: true,
          tracks: (out.tracks as Record<string, unknown>[]).map((t) => ({
            id: String(t.track_id),
            title: String(t.title ?? ""),
            seconds: Number(t.seconds ?? 0),
            audio_url: String(t.audio_url ?? ""),
            ...(typeof t.stem === "string" ? { stem: t.stem } : {}),
          })),
        };
      }
    }
  });
  return result;
}

export type SeparateRequest = {
  source: AudioSource;
  model?: string;
  /** the parts to keep; all of them when left out */
  stems?: string[];
};

/** Split a recording into stems. Every part is kept in Your music. */
export function separateAudio(
  runs: Runs,
  request: SeparateRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<ToolResult> {
  const input: Record<string, unknown> = { task: "separate", ...sourceInput(request.source) };
  if (request.model) input.model = request.model;
  if (request.stems?.length) input.stems = request.stems;
  return followTool(runs, input, signal, onStep);
}

export type ConvertRequest = {
  source: AudioSource;
  /** a saved voice made from a recording */
  voice: string;
  model?: string;
  seed?: number;
  title?: string;
};

/** Make a recording sound like a saved voice. */
export function convertVoice(
  runs: Runs,
  request: ConvertRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<ToolResult> {
  const input: Record<string, unknown> = {
    task: "convert",
    ...sourceInput(request.source),
    saved_voice: request.voice,
  };
  if (request.model) input.model = request.model;
  if (request.seed !== undefined) input.seed = request.seed;
  if (request.title?.trim()) input.title = request.title;
  return followTool(runs, input, signal, onStep);
}

export type EditWordsRequest = {
  source: AudioSource;
  /** what the recording says now */
  oldText: string;
  /** what it should say */
  newText: string;
  model?: string;
  seed?: number;
  title?: string;
  options?: Record<string, unknown>;
};

/** Change some words in a recording; the voice and the rest of the speech stay. */
export function editWords(
  runs: Runs,
  request: EditWordsRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<ToolResult> {
  const input: Record<string, unknown> = {
    task: "speech_edit",
    ...sourceInput(request.source),
    old_text: request.oldText,
    text: request.newText,
  };
  if (request.model) input.model = request.model;
  if (request.seed !== undefined) input.seed = request.seed;
  if (request.title?.trim()) input.title = request.title;
  if (request.options && Object.keys(request.options).length) input.options = request.options;
  return followTool(runs, input, signal, onStep);
}

export type ClipRequest = {
  /** the id of a picture added with `addPicture` */
  picture: string;
  /** what the person said the picture is */
  pictureBasis: PictureBasis;
  /** a recording of the library, or ... */
  source?: AudioSource;
  /** ... words to be spoken here (then the voice is always "generated") */
  text?: string;
  voice?: string;
  voiceBasis: VoiceBasis;
  model?: string;
  title?: string;
};

export type ClipResult =
  | { ok: true; clip: { id: string; title: string; seconds: number; video_url: string } }
  | { ok: false; code: string; message: string };

/** Make a talking video and follow the run to its end. It can take many minutes; the clip is saved by
 * the engine, so the caller reads the list again afterwards. */
export async function makeClip(
  runs: Runs,
  request: ClipRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<ClipResult> {
  let result: ClipResult = {
    ok: false,
    code: "lost",
    message:
      "We lost the connection while it was being made. It may still finish: look in Your videos.",
  };
  const input: Record<string, unknown> = {
    task: "lipsync",
    picture: request.picture,
    picture_basis: request.pictureBasis,
    voice_basis: request.voiceBasis,
  };
  if (request.text?.trim()) {
    input.text = request.text;
    if (request.voice) input.voice = request.voice;
  } else if (request.source) Object.assign(input, sourceInput(request.source));
  if (request.model) input.model = request.model;
  if (request.title?.trim()) input.title = request.title;
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
      } else if (typeof out.clip_id === "string") {
        result = {
          ok: true,
          clip: {
            id: out.clip_id,
            title: String(out.title ?? ""),
            seconds: Number(out.seconds ?? 0),
            video_url: String(out.video_url ?? ""),
          },
        };
      }
    }
  });
  return result;
}

/** One line of a dub's script: when it is said, what was said, and what it becomes. */
export type DubLine = { start: number; end: number; source: string; text: string };

export type DubScript = {
  segments: DubLine[];
  language: string;
  seconds: number;
  /** the voice and the background, kept in Your music when they were separated */
  vocalsTrack?: string;
  backgroundTrack?: string;
};

export type DubScriptResult =
  | { ok: true; script: DubScript }
  | { ok: false; code: string; message: string };

export type DubScriptRequest = {
  source: AudioSource;
  /** the language to dub into, such as "es" */
  language: string;
  /** separate the voice from the background first, to keep the background and clean the transcript */
  background?: boolean;
  transcribeModel?: string;
  separateModel?: string;
};

/** Write the script of a dub: separate, write down what is said with times, translate. The person
 * reads and changes it before `makeDub` speaks it. */
export async function dubScript(
  runs: Runs,
  request: DubScriptRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<DubScriptResult> {
  let result: DubScriptResult = {
    ok: false,
    code: "lost",
    message: "We lost the connection while the script was being written.",
  };
  const input: Record<string, unknown> = {
    task: "dub_script",
    ...sourceInput(request.source),
    language: request.language,
  };
  if (request.background) input.background = true;
  if (request.transcribeModel) input.transcribe_model = request.transcribeModel;
  if (request.separateModel) input.separate_model = request.separateModel;
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
          message: refusal.message ?? "That could not be written.",
        };
      } else if (Array.isArray(out.segments)) {
        result = {
          ok: true,
          script: {
            segments: out.segments as DubLine[],
            language: String(out.language ?? request.language),
            seconds: Number(out.seconds ?? 0),
            ...(typeof out.vocals_track === "string" ? { vocalsTrack: out.vocals_track } : {}),
            ...(typeof out.background_track === "string"
              ? { backgroundTrack: out.background_track }
              : {}),
          },
        };
      }
    }
  });
  return result;
}

export type VoiceFrom = "speaker" | "saved" | "builtin";
export type SpeakerBasis = "own" | "permission";

export type DubRequest = {
  source: AudioSource;
  language: string;
  /** the script, as the person left it */
  segments: DubLine[];
  voiceFrom: VoiceFrom;
  /** copying the speaker's voice needs the person's word that it is theirs or allowed */
  speakerBasis?: SpeakerBasis;
  savedVoice?: string;
  voice?: string;
  model?: string;
  vocalsTrack?: string;
  backgroundTrack?: string;
  title?: string;
};

export type DubFit = { lines: number; sped_up: number; max_overflow_s: number; elapsed_s: number };

export type DubResult =
  | { ok: true; track: Pick<Track, "id" | "title" | "seconds" | "audio_url">; fit: DubFit }
  | { ok: false; code: string; message: string };

/** Speak the script and mix it over the background: the dub is kept in Your music. */
export async function makeDub(
  runs: Runs,
  request: DubRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<DubResult> {
  let result: DubResult = {
    ok: false,
    code: "lost",
    message:
      "We lost the connection while the dub was being made. It may still finish: look in Your music.",
  };
  const input: Record<string, unknown> = {
    task: "dub",
    ...sourceInput(request.source),
    language: request.language,
    segments: request.segments,
    voice_from: request.voiceFrom,
  };
  if (request.speakerBasis) input.speaker_basis = request.speakerBasis;
  if (request.savedVoice) input.saved_voice = request.savedVoice;
  if (request.voice) input.voice = request.voice;
  if (request.model) input.model = request.model;
  if (request.vocalsTrack) input.vocals_track = request.vocalsTrack;
  if (request.backgroundTrack) input.background_track = request.backgroundTrack;
  if (request.title?.trim()) input.title = request.title;
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
          fit: (out.fit as DubFit) ?? { lines: 0, sped_up: 0, max_overflow_s: 0, elapsed_s: 0 },
        };
      }
    }
  });
  return result;
}

export type BookRequest = {
  title: string;
  chapters: { title: string; text: string }[];
  /** a built-in voice of the model, or ... */
  voice?: string;
  /** ... a voice the person saved */
  savedVoice?: string;
  model?: string;
  options?: Record<string, unknown>;
  /** also one track of the whole book (for books up to about two hours) */
  whole?: boolean;
  /** speak each chapter's title first (the default) */
  readTitles?: boolean;
};

export type BookResult =
  | {
      ok: true;
      tracks: (ToolTrack & { chapter: number })[];
      book: ToolTrack | null;
      seconds: number;
    }
  | { ok: false; code: string; message: string };

/** Speak a book chapter by chapter. Each chapter is kept in Your music as soon as it is done, so a
 * failure or a cancel leaves the earlier chapters there. */
export async function makeAudiobook(
  runs: Runs,
  request: BookRequest,
  signal: AbortSignal,
  onStep?: (label: string) => void,
): Promise<BookResult> {
  let result: BookResult = {
    ok: false,
    code: "lost",
    message:
      "We lost the connection while the book was being made. The chapters that were done are in Your music.",
  };
  const input: Record<string, unknown> = {
    task: "audiobook",
    title: request.title,
    chapters: request.chapters,
  };
  if (request.voice) input.voice = request.voice;
  if (request.savedVoice) input.saved_voice = request.savedVoice;
  if (request.model) input.model = request.model;
  if (request.options && Object.keys(request.options).length) input.options = request.options;
  if (request.whole) input.whole = true;
  if (request.readTitles === false) input.read_titles = false;
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
      } else if (Array.isArray(out.tracks)) {
        const track = (t: Record<string, unknown>): ToolTrack => ({
          id: String(t.track_id),
          title: String(t.title ?? ""),
          seconds: Number(t.seconds ?? 0),
          audio_url: String(t.audio_url ?? ""),
        });
        result = {
          ok: true,
          tracks: (out.tracks as Record<string, unknown>[]).map((t) => ({
            ...track(t),
            chapter: Number(t.chapter ?? 0),
          })),
          book: out.book ? track(out.book as Record<string, unknown>) : null,
          seconds: Number(out.seconds ?? 0),
        };
      }
    }
  });
  return result;
}
