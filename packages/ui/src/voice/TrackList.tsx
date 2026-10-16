"use client";

import type { Track, VoiceApi } from "@wasifyai/client";
import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/button";
import { Spinner } from "../components/spinner";
import { clock } from "./format";

/** The music that was made: play, save as a file, rename, delete. */
export function TrackList({
  api,
  refreshKey,
  modelTitle,
  heading = "Made before",
}: {
  api: VoiceApi;
  /** change it to read the list again (after something new was made) */
  refreshKey?: unknown;
  modelTitle?: (id: string) => string;
  heading?: string;
}) {
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: refreshKey asks for a new read
  const load = useCallback(
    () =>
      api
        .tracks()
        .then(setTracks)
        .catch((e) =>
          setProblem(e instanceof Error ? e.message : "The music could not be listed."),
        ),
    [api, refreshKey],
  );
  useEffect(() => {
    void load();
  }, [load]);

  async function save(t: Track) {
    const blob = await api.downloadTrack(t.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${t.title.replace(/[^\w -]+/g, "_") || "music"}.wav`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function rename(t: Track) {
    const next = window.prompt("Name this piece", t.title)?.trim();
    if (!next || next === t.title) return;
    const saved = await api.renameTrack(t.id, next);
    setTracks((list) => (list ?? []).map((x) => (x.id === t.id ? saved : x)));
  }

  async function remove(id: string) {
    await api.removeTrack(id);
    setTracks((list) => (list ?? []).filter((x) => x.id !== id));
  }

  if (problem) {
    return (
      <p role="alert" className="text-destructive">
        {problem}
      </p>
    );
  }
  if (tracks === null) return <Spinner />;
  if (tracks.length === 0) return <p className="text-muted-foreground">Nothing made yet.</p>;
  return (
    <section aria-label={heading} className="grid gap-3">
      <h2 className="font-semibold">{heading}</h2>
      <ul className="grid gap-3">
        {tracks.map((t) => (
          <li key={t.id} className="grid gap-2 rounded-xl border bg-card p-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-medium">{t.title}</span>
              <span className="text-muted-foreground text-xs">
                {t.mode === "sfx" ? "sound effect" : t.instrumental ? "instrumental" : "song"} ·{" "}
                {clock(t.seconds)} · {modelTitle?.(t.model_id) ?? t.model_id}
              </span>
            </div>
            <p className="line-clamp-2 text-muted-foreground text-sm">{t.description}</p>
            {/* biome-ignore lint/a11y/useMediaCaption: music; the description and lyrics are on the page */}
            <audio controls preload="none" src={t.audio_url} className="h-10 w-full" />
            <div className="flex flex-wrap gap-1">
              <Button size="sm" variant="ghost" onClick={() => void save(t)}>
                Save
              </Button>
              <Button size="sm" variant="ghost" onClick={() => void rename(t)}>
                Rename
              </Button>
              <Button size="sm" variant="ghost" onClick={() => void remove(t.id)}>
                Delete
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
