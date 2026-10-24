// My creations (ADR-0040, ADR-0041): every kind a person made, listed and searched in one place. The product list routes and
// `/creations/search` are the same on the web and the desktop; only the transport differs.
import type { SearchResponse } from "@wasifyai/contracts";
import type { ImagePage } from "./images";
import { HttpError, type Transport, errorMessage } from "./transport";
import type { VideoPage } from "./videos";
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

export type CreationKind = "track" | "image" | "video" | "speech" | "transcript" | "lipsync";

/** What the first screen shows: the latest of each kind. A kind that could not be read is listed in `failed`. */
export type Recent = {
  images: ImagePage | null;
  videos: VideoPage | null;
  songs: SongCard[];
  speeches: SpeechCard[];
  transcripts: TranscriptCard[];
  lipsyncs: LipSyncCard[];
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
};

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
      return {
        images,
        videos,
        songs: tracks?.items.map(trackFromVoice) ?? [],
        speeches: speeches?.items.map(speechFromVoice) ?? [],
        transcripts: transcripts?.items.map(transcriptFromVoice) ?? [],
        lipsyncs: clips?.items.map(clipFromVoice) ?? [],
      };
    },
  };
}
