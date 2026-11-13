"use client";
// What the rail and the Add tab show: the library, filtered by this project. The project keeps only tags;
// what a thing is called and looks like is read from the library, so a thing deleted there goes from here too.
import type {
  CreationKind,
  CreationsApi,
  CreativeApi,
  Found,
  ProjectMedia,
} from "@wasifyai/client";
import { useCallback, useEffect, useState } from "react";
import { type Entry, latestEntries } from "../creations/model";

const MANY = 200;
const IDS_A_REQUEST = 50; // the products' list routes take about 2000 characters of ids

/** Every entry of these cards, newest first. */
export function entriesOf(found: Found): Entry[] {
  const compositions = found.others.compositions.map(
    (composition): Entry => ({
      kind: "composition",
      id: composition.id,
      createdAt: composition.created_at,
      composition,
    }),
  );
  return [...latestEntries({ ...found, failed: [] }, MANY), ...compositions].sort(
    (a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt),
  );
}

export type ProjectCreations = Pick<CreationsApi, "recent" | "cards">;

export function useProjectMedia(
  api: CreativeApi,
  creations: ProjectCreations | undefined,
  id: string,
  songId: string | undefined,
  /** changes when something was made for the project */
  version = 0,
) {
  const [tags, setTags] = useState<ProjectMedia[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [problem, setProblem] = useState<string | null>(null);

  const show = useCallback(
    async (now: ProjectMedia[]) => {
      setTags(now);
      if (!creations) return;
      const all: [CreationKind, string][] = songId ? [["track", songId]] : [];
      for (const m of now) all.push([m.kind as CreationKind, m.item_id]);
      const parts: (typeof all)[] = [];
      for (let i = 0; i < all.length; i += IDS_A_REQUEST) {
        parts.push(all.slice(i, i + IDS_A_REQUEST));
      }
      const found = await Promise.all(
        parts.map((part) => {
          const ids: Partial<Record<CreationKind, string[]>> = {};
          for (const [kind, item] of part) ids[kind] = [...(ids[kind] ?? []), item];
          return creations.cards(ids);
        }),
      );
      setEntries(
        found.flatMap(entriesOf).sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt)),
      );
    },
    [creations, songId],
  );

  const run = useCallback(
    async (work: () => Promise<ProjectMedia[]>) => {
      setProblem(null);
      try {
        await show(await work());
      } catch (e) {
        setProblem(e instanceof Error ? e.message : "That did not work.");
      }
    },
    [show],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: version says when to read again
  useEffect(() => {
    void run(() => api.media(id));
  }, [api, id, run, version]);

  return {
    tags,
    entries,
    problem,
    add: (kind: string, itemId: string, shotId?: string) =>
      run(() => api.addMedia(id, kind, itemId, shotId)),
    remove: (kind: string, itemId: string) => run(() => api.removeMedia(id, kind, itemId)),
  };
}
