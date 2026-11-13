// My creations (ADR-0040, ADR-0041): every kind a person made, listed and searched in one place. The product list routes and
// `/creations/search` are the same on the web and the desktop; only the transport differs.
import type { SearchResponse } from "@wasifyai/contracts";
import type { CreativeProject } from "./creative";
import type { ImagePage, ImageSummary } from "./images";
import type { Model3d } from "./model3d";
import type { NotebookSummary } from "./notebooks";
import type { TrainedModel } from "./training";
import { HttpError, type Transport, errorMessage } from "./transport";
import type { BuilderProject } from "./videobuilder";
import type { VideoPage, VideoSummary } from "./videos";
import {
  type LipSyncCard,
  type SongCard,
  type SpeechCard,
  type TranscriptCard,
  type VoiceClip,
  type VoiceSpeech,
  type VoiceTrack,
  type VoiceTranscript,
  clipFromVoice,
  speechFromVoice,
  trackFromVoice,
  transcriptFromVoice,
} from "./voice-cards";

/** Why a search could not be answered, in words for a person. */
export class SearchError extends Error {}

export type CreationKind =
  | "track"
  | "image"
  | "video"
  | "speech"
  | "transcript"
  | "lipsync"
  | "model3d"
  | "composition"
  | "creative_project"
  | "notebook"
  | "taught";

/** The search index's names for the models a person taught (Train models): one kind in the Library. */
export const TAUGHT_KINDS = ["lora", "writing", "decision"] as const;

/** What the Library lists of the kinds that live in their own tools: 3D models, motion graphics, notebooks
 * and taught models (ADR-0093, U8). Each is empty where the service does not offer it. */
export type Others = {
  models3d: Model3d[];
  compositions: BuilderProject[];
  creativeProjects: CreativeProject[];
  notebooks: NotebookSummary[];
  taught: TrainedModel[];
};

/** What the first screen shows: the latest of each kind. A kind that could not be read is listed in `failed`. */
export type Recent = {
  images: ImagePage | null;
  videos: VideoPage | null;
  songs: SongCard[];
  speeches: SpeechCard[];
  transcripts: TranscriptCard[];
  lipsyncs: LipSyncCard[];
  others: Others;
  failed: ("images" | "videos" | "voice")[];
};

/** The cards for the ids a search ranked, by kind (a kind with no hit is empty). */
export type Found = {
  images: ImagePage | null;
  videos: VideoPage | null;
  songs: SongCard[];
  speeches: SpeechCard[];
  transcripts: TranscriptCard[];
  lipsyncs: LipSyncCard[];
  others: Others;
};

/** What was made from a picture, a clip or a track (ADR-0093, U8): changes of a picture and the clips that animate
 * it, the clips that carry a clip on, the changes, parts and dubs of a track. */
export type MadeFrom = { images: ImageSummary[]; videos: VideoSummary[]; songs: SongCard[] };

export type CreationsApi = {
  recent(): Promise<Recent>;
  moreImages(before: string, limit: number): Promise<ImagePage>;
  moreVideos(before: string, limit: number): Promise<VideoPage>;
  search(
    query: string,
    limit: number,
    kind?: CreationKind,
    signal?: AbortSignal,
  ): Promise<SearchResponse>;
  /** the cards for these ids of each kind, as the products' own list routes sign their files' links */
  cards(ids: Partial<Record<CreationKind, string[]>>, signal?: AbortSignal): Promise<Found>;
  /** what was made from this picture, clip or track */
  madeFrom(kind: "image" | "video" | "track", id: string): Promise<MadeFrom>;
  /** delete one thing for good (its product's own delete route) */
  remove(kind: CreationKind, id: string): Promise<void>;
  /** add a recording of the person's own to their music (it can then be split, dubbed, changed) */
  addRecording(file: File): Promise<SongCard>;
};

const NONE: Others = {
  models3d: [],
  compositions: [],
  creativeProjects: [],
  notebooks: [],
  taught: [],
};

const VOICE = "/products/wasifyai-voice";

export function createCreationsApi(transport: Transport): CreationsApi {
  async function json<T>(path: string, signal?: AbortSignal): Promise<T> {
    const res = await transport.fetch(path, { signal });
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }
  /** a product that is not there (the older speech products are retired where voice is on) is no results */
  async function optional<T>(p: Promise<T>): Promise<T | null> {
    try {
      return await p;
    } catch {
      return null;
    }
  }
  const voice = <T>(route: string, query: string, signal?: AbortSignal) =>
    optional(json<{ items: T[] }>(`${VOICE}/${route}?${query}`, signal));
  /** the kinds that live in their own tools: every one optional (a service may not offer it) */
  async function others(signal?: AbortSignal): Promise<Others> {
    const [models3d, compositions, creativeProjects, notebooks, taught] = await Promise.all([
      optional(json<{ items: Model3d[] }>("/products/wasifyai-model3d/m3d/models", signal)),
      optional(
        json<{ items: BuilderProject[] }>("/products/wasifyai-video/builder/projects", signal),
      ),
      optional(
        json<{ items: CreativeProject[] }>("/products/wasifyai-creative/creative/projects", signal),
      ),
      optional(json<NotebookSummary[]>("/products/wasifyai-notebooks/notebooks", signal)),
      optional(
        json<{ models: TrainedModel[] }>("/products/wasifyai-training/train/models", signal),
      ),
    ]);
    return {
      models3d: models3d?.items ?? [],
      compositions: compositions?.items ?? [],
      creativeProjects: creativeProjects?.items ?? [],
      notebooks: Array.isArray(notebooks) ? notebooks : [],
      taught: taught?.models ?? [],
    };
  }
  async function none(path: string, init: RequestInit): Promise<void> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok && res.status !== 404) throw new HttpError(res.status, await errorMessage(res));
  }

  return {
    async recent() {
      const settled = await Promise.allSettled([
        json<ImagePage>("/products/wasifyai-image/images?limit=12"),
        json<VideoPage>("/products/wasifyai-video/videos?limit=12"),
        json<{ items: VoiceTrack[] }>(`${VOICE}/tracks?limit=100`),
        json<{ items: VoiceSpeech[] }>(`${VOICE}/speeches?limit=100`),
        json<{ items: VoiceTranscript[] }>(`${VOICE}/transcripts?limit=100`),
        json<{ items: VoiceClip[] }>(`${VOICE}/clips?limit=100`),
      ]);
      const ok = <T>(r: PromiseSettledResult<T>) => (r.status === "fulfilled" ? r.value : null);
      const [images, videos, tracks, speeches, transcripts, clips] = settled;
      const more = await others();
      const failed: Recent["failed"] = [];
      if (images.status === "rejected") failed.push("images");
      if (videos.status === "rejected") failed.push("videos");
      if (settled.slice(2).some((r) => r.status === "rejected")) failed.push("voice");
      return {
        images: ok(images),
        videos: ok(videos),
        songs: ok(tracks)?.items.map(trackFromVoice) ?? [],
        speeches: ok(speeches)?.items.map(speechFromVoice) ?? [],
        transcripts: ok(transcripts)?.items.map(transcriptFromVoice) ?? [],
        lipsyncs: ok(clips)?.items.map(clipFromVoice) ?? [],
        others: more,
        failed,
      };
    },

    moreImages: (before, limit) =>
      json<ImagePage>(
        `/products/wasifyai-image/images?limit=${limit}&before=${encodeURIComponent(before)}`,
      ),
    moreVideos: (before, limit) =>
      json<VideoPage>(
        `/products/wasifyai-video/videos?limit=${limit}&before=${encodeURIComponent(before)}`,
      ),

    async search(query, limit, kind, signal) {
      const params = new URLSearchParams({ q: query, limit: String(limit) });
      if (kind) params.set("kind", kind);
      const res = await transport.fetch(`/creations/search?${params}`, { signal });
      if (res.status === 401) transport.onUnauthorized?.();
      if (res.status === 429) {
        throw new SearchError("You've searched a lot. Please wait a while and try again.");
      }
      if (res.status === 422) throw new SearchError("Please type at least two characters.");
      if (!res.ok) throw new SearchError("Search isn't available right now. Please try again.");
      return (await res.json()) as SearchResponse;
    },

    async cards(ids, signal) {
      const q = (kind: CreationKind) => `ids=${(ids[kind] ?? []).join(",")}`;
      const has = (kind: CreationKind) => (ids[kind]?.length ?? 0) > 0;
      const [images, videos, speeches, transcripts, tracks, clips] = await Promise.all([
        has("image")
          ? json<ImagePage>(`/products/wasifyai-image/images?${q("image")}`, signal)
          : null,
        has("video")
          ? json<VideoPage>(`/products/wasifyai-video/videos?${q("video")}`, signal)
          : null,
        // hits carry no product, but speech, music and video are all the voice product's now
        has("speech") ? voice<VoiceSpeech>("speeches", q("speech"), signal) : null,
        has("transcript") ? voice<VoiceTranscript>("transcripts", q("transcript"), signal) : null,
        has("track") ? voice<VoiceTrack>("tracks", q("track"), signal) : null,
        has("lipsync") ? voice<VoiceClip>("clips", q("lipsync"), signal) : null,
      ]);
      // the tools' own kinds are few: their lists are read whole and the hits picked out
      const wantedOthers =
        has("model3d") ||
        has("composition") ||
        has("creative_project") ||
        has("notebook") ||
        has("taught");
      const all = wantedOthers ? await others(signal) : NONE;
      const pick = <T extends { id: string }>(items: T[], kind: CreationKind) => {
        const set = new Set(ids[kind] ?? []);
        return items.filter((x) => set.has(x.id));
      };
      return {
        images,
        videos,
        songs: tracks?.items.map(trackFromVoice) ?? [],
        speeches: speeches?.items.map(speechFromVoice) ?? [],
        transcripts: transcripts?.items.map(transcriptFromVoice) ?? [],
        lipsyncs: clips?.items.map(clipFromVoice) ?? [],
        others: {
          models3d: pick(all.models3d, "model3d"),
          compositions: pick(all.compositions, "composition"),
          creativeProjects: pick(all.creativeProjects, "creative_project"),
          notebooks: pick(all.notebooks, "notebook"),
          taught: pick(all.taught, "taught"),
        },
      };
    },

    async madeFrom(kind, id) {
      const at = encodeURIComponent(id);
      if (kind === "track") {
        const tracks = await voice<VoiceTrack>("tracks", "limit=200");
        return {
          images: [],
          videos: [],
          songs: (tracks?.items ?? []).filter((t) => t.parent_id === id).map(trackFromVoice),
        };
      }
      const [images, videos] = await Promise.all([
        kind === "image"
          ? optional(json<ImagePage>(`/products/wasifyai-image/images?limit=24&source=${at}`))
          : null,
        optional(json<VideoPage>(`/products/wasifyai-video/videos?limit=24&source=${at}`)),
      ]);
      return { images: images?.images ?? [], videos: videos?.videos ?? [], songs: [] };
    },

    remove(kind, id) {
      const at = encodeURIComponent(id);
      const path = {
        image: `/products/wasifyai-image/images/${at}`,
        video: `/products/wasifyai-video/videos/${at}`,
        track: `${VOICE}/tracks/${at}`,
        speech: `${VOICE}/speeches/${at}`,
        transcript: `${VOICE}/transcripts/${at}`,
        lipsync: `${VOICE}/clips/${at}`,
        model3d: `/products/wasifyai-model3d/m3d/models/${at}`,
        composition: `/products/wasifyai-video/builder/projects/${at}`,
        creative_project: `/products/wasifyai-creative/creative/projects/${at}`,
        notebook: `/products/wasifyai-notebooks/notebooks/${at}`,
        taught: `/products/wasifyai-training/train/models/${at}`,
      }[kind];
      return none(path, { method: "DELETE" });
    },

    async addRecording(file) {
      const form = new FormData();
      form.append("file", file, file.name);
      const res = await transport.fetch(`${VOICE}/tracks/import`, { method: "POST", body: form });
      if (res.status === 401) transport.onUnauthorized?.();
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
      return trackFromVoice((await res.json()) as VoiceTrack);
    },
  };
}
