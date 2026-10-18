"use client";

import type { Entry, Filter } from "@/lib/creations";
import { kindOf, longEnough } from "@/lib/creations";
import {
  clipFromVoice,
  speechFromVoice,
  trackFromVoice,
  transcriptFromVoice,
} from "@/lib/voice-cards";
import type { ImagePage, SearchResponse, VideoPage } from "@wasifyai/contracts";
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

/** A product that is not there (the older speech products are retired where voice is on) is no results,
 * not a failed search. */
async function optional<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch {
    return null;
  }
}

/** The ids of one kind, asked of that product's own list route (only a product can sign its files'
 * links), then put back in the order search ranked them. */
async function cards(response: SearchResponse, signal: AbortSignal): Promise<Entry[]> {
  const by = (kind: string) => response.results.filter((r) => r.kind === kind);
  const ids = (kind: string) =>
    by(kind)
      .map((r) => r.id)
      .join(",");
  const list = <T>(kind: string, route: string) =>
    by(kind).length
      ? optional(
          getJson<{ items: T[] }>(`/api/products/wasifyai-voice/${route}?ids=${ids(kind)}`, signal),
        )
      : null;
  const [images, videos, speeches, transcripts, tracks, clips] = await Promise.all([
    by("image").length
      ? getJson<ImagePage>(`/api/products/wasifyai-image/images?ids=${ids("image")}`, signal)
      : null,
    by("video").length
      ? getJson<VideoPage>(`/api/products/wasifyai-video/videos?ids=${ids("video")}`, signal)
      : null,
    // hits carry no product, but speech, music and video are all the voice product's now
    list<Parameters<typeof speechFromVoice>[0]>("speech", "speeches"),
    list<Parameters<typeof transcriptFromVoice>[0]>("transcript", "transcripts"),
    list<Parameters<typeof trackFromVoice>[0]>("track", "tracks"),
    list<Parameters<typeof clipFromVoice>[0]>("lipsync", "clips"),
  ]);
  const found = new Map<string, Entry>();
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
  for (const item of speeches?.items ?? []) {
    const speech = speechFromVoice(item);
    found.set(`speech:${speech.id}`, {
      kind: "speech",
      id: speech.id,
      createdAt: speech.created_at,
      speech,
    });
  }
  for (const item of transcripts?.items ?? []) {
    const transcript = transcriptFromVoice(item);
    found.set(`transcript:${transcript.id}`, {
      kind: "transcript",
      id: transcript.id,
      createdAt: transcript.created_at,
      transcript,
    });
  }
  for (const item of tracks?.items ?? []) {
    const song = trackFromVoice(item);
    found.set(`track:${song.id}`, { kind: "song", id: song.id, createdAt: song.created_at, song });
  }
  for (const item of clips?.items ?? []) {
    const lipsync = clipFromVoice(item);
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
