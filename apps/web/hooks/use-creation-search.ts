"use client";

import type { Entry, Filter } from "@/lib/creations";
import { kindOf, longEnough } from "@/lib/creations";
import type {
  ImagePage,
  LipSyncPage,
  SearchResponse,
  SongPage,
  SpeechPage,
  TranscriptPage,
  VideoPage,
} from "@wasifyai/contracts";
import { useEffect, useState } from "react";

export const DEBOUNCE_MS = 300;
const LIMIT = 30;

export type SearchState =
  | { status: "idle" }
  | { status: "searching"; query: string }
  | { status: "done"; query: string; entries: Entry[]; degraded: boolean; words: Set<string> }
  | { status: "error"; query: string; message: string };

class SearchError extends Error {}

async function getJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.assign(`/signin?next=${encodeURIComponent(window.location.pathname)}`);
  }
  if (res.status === 429) {
    throw new SearchError("You've searched a lot. Please wait a while and try again.");
  }
  if (res.status === 422) throw new SearchError("Please type at least two characters.");
  if (!res.ok) throw new SearchError("Search isn't available right now. Please try again.");
  return (await res.json()) as T;
}

/** The ids of one kind, asked of that product's own list route (only a product can sign its files'
 * links), then put back in the order search ranked them. */
async function cards(response: SearchResponse, signal: AbortSignal): Promise<Entry[]> {
  const by = (kind: string) => response.results.filter((r) => r.kind === kind);
  const ids = (kind: string) =>
    by(kind)
      .map((r) => r.id)
      .join(",");
  const [songs, images, videos, speeches, transcripts, lipsyncs] = await Promise.all([
    by("song").length
      ? getJson<SongPage>(`/api/products/wasifyai-music/songs?ids=${ids("song")}`, signal)
      : null,
    by("image").length
      ? getJson<ImagePage>(`/api/products/wasifyai-image/images?ids=${ids("image")}`, signal)
      : null,
    by("video").length
      ? getJson<VideoPage>(`/api/products/wasifyai-video/videos?ids=${ids("video")}`, signal)
      : null,
    by("speech").length
      ? getJson<SpeechPage>(`/api/products/wasifyai-tts/speeches?ids=${ids("speech")}`, signal)
      : null,
    by("transcript").length
      ? getJson<TranscriptPage>(
          `/api/products/wasifyai-stt/transcripts?ids=${ids("transcript")}`,
          signal,
        )
      : null,
    by("lipsync").length
      ? getJson<LipSyncPage>(
          `/api/products/wasifyai-lipsync/lipsyncs?ids=${ids("lipsync")}`,
          signal,
        )
      : null,
  ]);
  const found = new Map<string, Entry>();
  for (const song of songs?.songs ?? []) {
    found.set(`song:${song.id}`, { kind: "song", id: song.id, createdAt: song.created_at, song });
  }
  for (const image of images?.images ?? []) {
    found.set(`image:${image.id}`, {
      kind: "image",
      id: image.id,
      createdAt: image.created_at,
      image,
    });
  }
  for (const video of videos?.videos ?? []) {
    found.set(`video:${video.id}`, {
      kind: "video",
      id: video.id,
      createdAt: video.created_at,
      video,
    });
  }
  for (const speech of speeches?.speeches ?? []) {
    found.set(`speech:${speech.id}`, {
      kind: "speech",
      id: speech.id,
      createdAt: speech.created_at,
      speech,
    });
  }
  for (const transcript of transcripts?.transcripts ?? []) {
    found.set(`transcript:${transcript.id}`, {
      kind: "transcript",
      id: transcript.id,
      createdAt: transcript.created_at,
      transcript,
    });
  }
  for (const lipsync of lipsyncs?.lipsyncs ?? []) {
    found.set(`lipsync:${lipsync.id}`, {
      kind: "lipsync",
      id: lipsync.id,
      createdAt: lipsync.created_at,
      lipsync,
    });
  }
  return response.results.flatMap((r) => found.get(`${r.kind}:${r.id}`) ?? []);
}

/**
 * Search over My creations (ADR-0041): waits for the user to stop typing, asks the search API, then
 * fetches the cards for the ids it returned. Fewer than two characters is not a search.
 */
export function useCreationSearch(query: string, filter: Filter): SearchState {
  const [state, setState] = useState<SearchState>({ status: "idle" });
  const text = query.trim().replace(/\s+/g, " ");

  useEffect(() => {
    if (!longEnough(text)) {
      setState({ status: "idle" });
      return;
    }
    const ctrl = new AbortController();
    setState({ status: "searching", query: text });
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: text, limit: String(LIMIT) });
        const kind = kindOf(filter);
        if (kind) params.set("kind", kind);
        const response = await getJson<SearchResponse>(
          `/api/creations/search?${params}`,
          ctrl.signal,
        );
        const entries = await cards(response, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setState({
          status: "done",
          query: text,
          entries,
          degraded: response.degraded,
          words: new Set(response.results.filter((r) => r.match === "words").map((r) => r.id)),
        });
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setState({
          status: "error",
          query: text,
          message:
            e instanceof SearchError
              ? e.message
              : "We couldn't reach the server. Check your connection and try again.",
        });
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [text, filter]);

  return state;
}
