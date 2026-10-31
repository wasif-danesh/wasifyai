"use client";

import { type CreationsApi, SearchError, TAUGHT_KINDS } from "@wasifyai/client";
import { useEffect, useState } from "react";
import { type Entry, type Filter, kindOf, longEnough } from "./model";

export const DEBOUNCE_MS = 300;
const LIMIT = 30;

export type SearchState =
  | { status: "idle" }
  | { status: "searching"; query: string }
  | { status: "done"; query: string; entries: Entry[]; degraded: boolean; words: Set<string> }
  | { status: "error"; query: string; message: string };

/** The cards for the ids a search ranked, put back in the order search ranked them. */
async function cards(
  api: CreationsApi,
  response: Awaited<ReturnType<CreationsApi["search"]>>,
  signal: AbortSignal,
): Promise<Entry[]> {
  const ids = (kind: string) => response.results.filter((r) => r.kind === kind).map((r) => r.id);
  const taught = new Set<string>(TAUGHT_KINDS);
  // the index's kind for a hit, as the Library names it: a taught model is one kind here
  const kindOfHit = (k: string) => (taught.has(k) ? "taught" : k);
  const found = await api.cards(
    {
      image: ids("image"),
      video: ids("video"),
      speech: ids("speech"),
      transcript: ids("transcript"),
      track: ids("track"),
      lipsync: ids("lipsync"),
      model3d: ids("model3d"),
      composition: ids("composition"),
      creative_project: ids("creative_project"),
      notebook: ids("notebook"),
      taught: response.results.filter((r) => taught.has(r.kind)).map((r) => r.id),
    },
    signal,
  );
  const byKey = new Map<string, Entry>();
  for (const image of found.images?.images ?? [])
    byKey.set(`image:${image.id}`, {
      kind: "image",
      id: image.id,
      createdAt: image.created_at,
      image,
    });
  for (const video of found.videos?.videos ?? [])
    byKey.set(`video:${video.id}`, {
      kind: "video",
      id: video.id,
      createdAt: video.created_at,
      video,
    });
  for (const speech of found.speeches)
    byKey.set(`speech:${speech.id}`, {
      kind: "speech",
      id: speech.id,
      createdAt: speech.created_at,
      speech,
    });
  for (const transcript of found.transcripts)
    byKey.set(`transcript:${transcript.id}`, {
      kind: "transcript",
      id: transcript.id,
      createdAt: transcript.created_at,
      transcript,
    });
  for (const song of found.songs)
    byKey.set(`track:${song.id}`, { kind: "song", id: song.id, createdAt: song.created_at, song });
  for (const lipsync of found.lipsyncs)
    byKey.set(`lipsync:${lipsync.id}`, {
      kind: "lipsync",
      id: lipsync.id,
      createdAt: lipsync.created_at,
      lipsync,
    });
  const { models3d, compositions, creativeProjects, notebooks, taught: models } = found.others;
  for (const model3d of models3d)
    byKey.set(`model3d:${model3d.id}`, {
      kind: "model3d",
      id: model3d.id,
      createdAt: model3d.created_at,
      model3d,
    });
  for (const composition of compositions)
    byKey.set(`composition:${composition.id}`, {
      kind: "composition",
      id: composition.id,
      createdAt: composition.updated_at || composition.created_at,
      composition,
    });
  for (const project of creativeProjects)
    byKey.set(`creative_project:${project.id}`, {
      kind: "creative_project",
      id: project.id,
      createdAt: project.updated_at || project.created_at,
      project,
    });
  for (const notebook of notebooks)
    byKey.set(`notebook:${notebook.id}`, {
      kind: "notebook",
      id: notebook.id,
      createdAt: notebook.updated_at || notebook.created_at,
      notebook,
    });
  for (const model of models)
    byKey.set(`taught:${model.id}`, {
      kind: "taught",
      id: model.id,
      createdAt: model.created_at,
      taught: model,
    });
  return response.results.flatMap((r) => byKey.get(`${kindOfHit(r.kind)}:${r.id}`) ?? []);
}

/**
 * Search over My creations (ADR-0041): waits for the user to stop typing, asks the search API, then
 * fetches the cards for the ids it returned. Fewer than two characters is not a search.
 */
export function useCreationSearch(api: CreationsApi, query: string, filter: Filter): SearchState {
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
        const wanted = kindOf(filter);
        // taught models are three kinds in the index: search them all and keep those
        const kind = (wanted === "taught" ? undefined : wanted) as Parameters<
          CreationsApi["search"]
        >[2];
        const raw = await api.search(text, LIMIT, kind, ctrl.signal);
        const response =
          wanted === "taught"
            ? {
                ...raw,
                results: raw.results.filter((r) =>
                  (TAUGHT_KINDS as readonly string[]).includes(r.kind),
                ),
              }
            : raw;
        const entries = await cards(api, response, ctrl.signal);
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
  }, [api, text, filter]);

  return state;
}
