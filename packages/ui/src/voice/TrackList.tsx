"use client";

import type { Track, VoiceApi } from "@wasifyai/client";
import { Heart } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Spinner } from "../components/spinner";
import { clock } from "./format";

const FORMAT_LABEL = { wav: "WAV", mp3: "MP3", m4a: "M4A" } as const;

/** What a track is, in a few words. */
export function trackKind(t: Track): string {
  if (t.mode === "edit") return `changed (${t.edit.action ?? "edit"})`;
  if (t.mode === "stem") return `part: ${t.edit.stem ?? "stem"}`;
  if (t.mode === "converted") return `in the voice of ${t.edit.voice ?? "another voice"}`;
  if (t.mode === "edited") return "words changed";
  if (t.mode === "imported") return "added from a file";
  if (t.mode === "dubbed") return `dubbed into ${t.edit.language ?? "another language"}`;
  if (t.mode === "chapter") return `chapter ${t.edit.chapter ?? ""} of ${t.edit.of ?? ""}`.trim();
  if (t.mode === "audiobook") return "audiobook";
  if (t.mode === "sfx") return "sound effect";
  return t.instrumental ? "instrumental" : "song";
}

/** Whether a track was made from a description (so it can be made again), not changed or added. */
const isMade = (t: Track) => t.mode === "song" || t.mode === "sfx";

export type TrackTool = "separate" | "convert" | "words";

/** The music that was made: play, favourite, save in a format the computer can make, make it again,
 * change it, rename, delete. With `searchable`, a box finds music by its name, description or lyrics. */
export function TrackList({
  api,
  refreshKey,
  modelTitle,
  heading = "Made before",
  searchable = false,
  onAgain,
  onTake,
  onEdit,
  onTool,
}: {
  api: VoiceApi;
  /** change it to read the list again (after something new was made) */
  refreshKey?: unknown;
  modelTitle?: (id: string) => string;
  heading?: string;
  searchable?: boolean;
  /** make it again with the same settings and seed (the same music) */
  onAgain?: (t: Track) => void;
  /** make it again with a new seed (another take) */
  onTake?: (t: Track) => void;
  /** open the editor for this track */
  onEdit?: (t: Track) => void;
  /** open an audio tool on this track: split it, change its voice, change its words */
  onTool?: (t: Track, tool: TrackTool) => void;
}) {
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [formats, setFormats] = useState<string[]>(["wav"]);
  const [problem, setProblem] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [onlyHearts, setOnlyHearts] = useState(false);

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
  useEffect(() => {
    api
      .formats()
      .then(setFormats)
      .catch(() => undefined);
  }, [api]);

  async function save(t: Track, format: "wav" | "mp3" | "m4a") {
    setProblem(null);
    try {
      const blob = await api.downloadTrack(t.id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${t.title.replace(/[^\w -]+/g, "_") || "music"}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be saved.");
    }
  }

  const change = (saved: Track) =>
    setTracks((list) => (list ?? []).map((x) => (x.id === saved.id ? saved : x)));

  async function rename(t: Track) {
    const next = window.prompt("Name this piece", t.title)?.trim();
    if (!next || next === t.title) return;
    change(await api.updateTrack(t.id, { title: next }));
  }

  async function heart(t: Track) {
    change(await api.updateTrack(t.id, { favourite: !t.favourite }));
  }

  async function remove(id: string) {
    await api.removeTrack(id);
    setTracks((list) => (list ?? []).filter((x) => x.id !== id));
  }

  if (tracks === null && !problem) return <Spinner />;
  const words = query.trim().toLowerCase();
  const shown = (tracks ?? []).filter(
    (t) =>
      (!onlyHearts || t.favourite) &&
      (!words || `${t.title} ${t.description} ${t.lyrics}`.toLowerCase().includes(words)),
  );
  return (
    <section aria-label={heading} className="grid gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="me-auto font-semibold">{heading}</h2>
        {searchable ? (
          <>
            <input
              type="search"
              aria-label="Search your music"
              placeholder="Search by name, style or words"
              className="h-9 w-64 rounded-md border border-input bg-transparent px-3 text-sm"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <label className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={onlyHearts}
                onChange={(e) => setOnlyHearts(e.target.checked)}
              />
              Favourites only
            </label>
          </>
        ) : null}
      </div>
      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : null}
      {tracks && tracks.length === 0 ? (
        <p className="text-muted-foreground">Nothing made yet.</p>
      ) : shown.length === 0 ? (
        <p className="text-muted-foreground">Nothing matches.</p>
      ) : null}
      <ul className="grid gap-3">
        {shown.map((t) => (
          <li key={t.id} className="grid gap-2 rounded-xl border bg-card p-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-medium">{t.title}</span>
              <span className="text-muted-foreground text-xs">
                {trackKind(t)} · {clock(t.seconds)}
                {t.model_id ? ` · ${modelTitle?.(t.model_id) ?? t.model_id}` : ""}
              </span>
              <button
                type="button"
                aria-pressed={t.favourite}
                aria-label={t.favourite ? "Remove from favourites" : "Add to favourites"}
                className="ms-auto rounded-md p-1 text-muted-foreground hover:bg-accent"
                onClick={() => void heart(t)}
              >
                <Heart className={cn("size-4", t.favourite && "fill-current text-primary")} />
              </button>
            </div>
            <p className="line-clamp-2 text-muted-foreground text-sm">{t.description}</p>
            {/* biome-ignore lint/a11y/useMediaCaption: music; the description and lyrics are on the page */}
            <audio controls preload="none" src={t.audio_url} className="h-10 w-full" />
            <div className="flex flex-wrap gap-1">
              {formats.map((f) => (
                <Button
                  key={f}
                  size="sm"
                  variant="ghost"
                  onClick={() => void save(t, f as "wav" | "mp3" | "m4a")}
                >
                  Save {FORMAT_LABEL[f as keyof typeof FORMAT_LABEL] ?? f.toUpperCase()}
                </Button>
              ))}
              {onAgain && isMade(t) ? (
                <Button size="sm" variant="ghost" onClick={() => onAgain(t)}>
                  Make it again
                </Button>
              ) : null}
              {onTake && isMade(t) ? (
                <Button size="sm" variant="ghost" onClick={() => onTake(t)}>
                  Another take
                </Button>
              ) : null}
              {onEdit && t.mode !== "imported" && t.mode !== "stem" ? (
                <Button size="sm" variant="ghost" onClick={() => onEdit(t)}>
                  Change it
                </Button>
              ) : null}
              {onTool ? (
                <>
                  <Button size="sm" variant="ghost" onClick={() => onTool(t, "separate")}>
                    Split into parts
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => onTool(t, "convert")}>
                    Change the voice
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => onTool(t, "words")}>
                    Change the words
                  </Button>
                </>
              ) : null}
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
