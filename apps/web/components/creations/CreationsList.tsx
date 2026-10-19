"use client";

import { Equaliser } from "@/components/Logo";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useCreationSearch } from "@/hooks/use-creation-search";
import type { Entry, Filter } from "@/lib/creations";
import { actions, empty, hint, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { LipSyncCard, SongCard, SpeechCard, TranscriptCard } from "@/lib/voice-cards";
import type { ImagePage, VideoPage } from "@wasifyai/contracts";
import { LayoutGrid, Table2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useMemo, useState } from "react";
import { CreationCard } from "./CreationCard";
import { CreationsTable } from "./CreationsTable";

const PAGE = 12;
const tiles =
  "m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,13rem),1fr))] items-stretch gap-4 p-0";
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "songs", label: "Music" },
  { value: "images", label: "Images" },
  { value: "videos", label: "Videos" },
  { value: "speeches", label: "Speech" },
  { value: "transcripts", label: "Transcripts" },
  { value: "lipsyncs", label: "Lip syncs" },
];

export function CreationsList({
  songs = [],
  images: imagePage,
  videos: videoPage = null,
  speeches = [],
  transcripts = [],
  lipsyncs = [],
  initialFilter = "all",
}: {
  /** the voice product's lists: the latest of each, with no further pages */
  songs?: SongCard[];
  images: ImagePage | null;
  videos?: VideoPage | null;
  speeches?: SpeechCard[];
  transcripts?: TranscriptCard[];
  lipsyncs?: LipSyncCard[];
  initialFilter?: Filter;
}) {
  const [images, setImages] = useState(imagePage?.images ?? []);
  const [videos, setVideos] = useState(videoPage?.videos ?? []);
  const [imageNext, setImageNext] = useState(imagePage?.next_before ?? null);
  const [videoNext, setVideoNext] = useState(videoPage?.next_before ?? null);
  const [filter, setFilter] = useState<Filter>(initialFilter);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const entries = useMemo<Entry[]>(() => {
    const all: Entry[] = [
      ...songs.map((song) => ({
        kind: "song" as const,
        id: song.id,
        createdAt: song.created_at,
        song,
      })),
      ...images.map((image) => ({
        kind: "image" as const,
        id: image.id,
        createdAt: image.created_at,
        image,
      })),
      ...videos.map((video) => ({
        kind: "video" as const,
        id: video.id,
        createdAt: video.created_at,
        video,
      })),
      ...speeches.map((speech) => ({
        kind: "speech" as const,
        id: speech.id,
        createdAt: speech.created_at,
        speech,
      })),
      ...transcripts.map((transcript) => ({
        kind: "transcript" as const,
        id: transcript.id,
        createdAt: transcript.created_at,
        transcript,
      })),
      ...lipsyncs.map((lipsync) => ({
        kind: "lipsync" as const,
        id: lipsync.id,
        createdAt: lipsync.created_at,
        lipsync,
      })),
    ];
    const wanted = {
      all: null,
      songs: "song",
      images: "image",
      videos: "video",
      speeches: "speech",
      transcripts: "transcript",
      lipsyncs: "lipsync",
    }[filter];
    return all
      .filter((entry) => wanted === null || entry.kind === wanted)
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
  }, [filter, images, lipsyncs, songs, speeches, transcripts, videos]);

  /** Load the next page of one kind. Returns true when it failed. */
  async function page<T>(url: string, apply: (p: T) => void): Promise<boolean> {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(String(res.status));
      apply((await res.json()) as T);
      return false;
    } catch {
      return true;
    }
  }

  async function more() {
    if (loading) return;
    setLoading(true);
    setFailed(false);
    const q = (before: string) => `limit=${PAGE}&before=${encodeURIComponent(before)}`;
    const jobs: Promise<boolean>[] = [];
    if (imageNext && (filter === "all" || filter === "images")) {
      jobs.push(
        page<ImagePage>(`/api/products/wasifyai-image/images?${q(imageNext)}`, (p) => {
          setImages((cur) => [...cur, ...p.images]);
          setImageNext(p.next_before ?? null);
        }),
      );
    }
    if (videoNext && (filter === "all" || filter === "videos")) {
      jobs.push(
        page<VideoPage>(`/api/products/wasifyai-video/videos?${q(videoNext)}`, (p) => {
          setVideos((cur) => [...cur, ...p.videos]);
          setVideoNext(p.next_before ?? null);
        }),
      );
    }
    const results = await Promise.all(jobs);
    setFailed(results.some(Boolean));
    setLoading(false);
  }

  const counts = {
    all:
      songs.length +
      images.length +
      videos.length +
      speeches.length +
      transcripts.length +
      lipsyncs.length,
    songs: songs.length,
    images: images.length,
    videos: videos.length,
    speeches: speeches.length,
    transcripts: transcripts.length,
    lipsyncs: lipsyncs.length,
  };
  const hasMore =
    filter === "all"
      ? Boolean(imageNext || videoNext)
      : filter === "images"
        ? Boolean(imageNext)
        : filter === "videos"
          ? Boolean(videoNext)
          : false;

  const [view, setView] = useState<"cards" | "table">("cards");
  useEffect(() => {
    try {
      if (localStorage.getItem("creations-view") === "table") setView("table");
    } catch {
      // storage can be blocked; the cards view is the default
    }
  }, []);
  function chooseView(next: string) {
    if (next !== "cards" && next !== "table") return; // clicking the chosen one again clears it; ignore
    setView(next);
    try {
      localStorage.setItem("creations-view", next);
    } catch {
      // not remembered, still works
    }
  }

  const [query, setQuery] = useState("");
  const searchId = useId();
  const search = useCreationSearch(query, filter);
  const searching = search.status !== "idle";
  const shown = search.status === "done" ? search.entries : entries;
  const isEmpty = !searching && entries.length === 0;

  return (
    <section className="grid gap-5" aria-label="Your creations">
      <search className="flex flex-wrap items-center gap-2">
        <Label htmlFor={searchId} className="sr-only">
          Search your creations
        </Label>
        <Input
          id={searchId}
          type="search"
          className="h-11 min-w-[min(100%,18rem)] flex-1"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by what it's about, in any language…"
          maxLength={200}
          autoComplete="off"
          enterKeyHint="search"
          aria-describedby={`${searchId}-hint`}
        />
        {query ? (
          <Button type="button" variant="outline" size="sm" onClick={() => setQuery("")}>
            Clear
          </Button>
        ) : null}
        <span className={cn(hint, "basis-full")} id={`${searchId}-hint`}>
          Try “rain in Madrid” or “zorro en la nieve”.
        </span>
      </search>

      <div className="flex flex-col items-start justify-between gap-4 pt-1 pb-2 min-[521px]:flex-row min-[521px]:items-center">
        <fieldset className="m-0 inline-flex min-w-0 gap-1 rounded-full border bg-surface p-[0.3rem] max-[520px]:w-full max-[520px]:justify-between">
          <legend className="sr-only">Filter creations</legend>
          {FILTERS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
              className="inline-flex items-center gap-[0.45rem] rounded-full border-0 bg-transparent px-[0.85rem] py-[0.55rem] text-ui font-semibold text-muted-foreground transition-colors hover:text-foreground aria-pressed:bg-accent aria-pressed:text-foreground max-[520px]:px-[0.7rem]"
            >
              {label} <span className="text-ui-sm opacity-70">{counts[value]}</span>
            </button>
          ))}
        </fieldset>
        <ToggleGroup
          type="single"
          value={view}
          onValueChange={chooseView}
          variant="outline"
          size="sm"
          aria-label="How to show your creations"
        >
          <ToggleGroupItem value="cards" aria-label="Cards">
            <LayoutGrid aria-hidden="true" />
          </ToggleGroupItem>
          <ToggleGroupItem value="table" aria-label="Table">
            <Table2 aria-hidden="true" />
          </ToggleGroupItem>
        </ToggleGroup>
        <span className="text-step--1 text-muted-foreground" aria-live="polite">
          {search.status === "searching" ? (
            "Searching…"
          ) : search.status === "done" ? (
            <>
              {search.entries.length} {search.entries.length === 1 ? "result" : "results"} for “
              {search.query}”
            </>
          ) : (
            <>
              {entries.length} {entries.length === 1 ? "creation" : "creations"}
            </>
          )}
        </span>
      </div>

      {search.status === "error" ? (
        <Notice tone="error" title="Search didn't work">
          {search.message}
        </Notice>
      ) : null}
      {search.status === "done" && search.degraded ? (
        <Notice tone="info" title="Showing exact word matches only">
          Search by meaning is not available right now.
        </Notice>
      ) : null}

      {search.status === "done" && search.entries.length === 0 ? (
        <div className={cn(panel, empty, "mt-4 mb-8")}>
          <h2 className="text-step-1 font-semibold">Nothing matched “{search.query}”</h2>
          <p>Try other words, or describe what it was about.</p>
          <Button type="button" variant="outline" onClick={() => setQuery("")}>
            Clear the search
          </Button>
        </div>
      ) : isEmpty ? (
        <div className={cn(panel, empty, "mt-4 mb-8")}>
          {filter === "all" || filter === "songs" ? <Equaliser still /> : null}
          <h2 className="text-step-1 font-semibold">
            {filter === "all"
              ? "Your creative space is ready"
              : `No ${filter === "speeches" ? "speech" : filter === "songs" ? "music" : filter} yet`}
          </h2>
          <p>Make something new and it will appear here.</p>
          <div className={actions}>
            <Button asChild>
              <Link href="/voice/music">Create music</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/image">Make an image</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/video">Make a video</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/voice/speak">Create speech</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/voice/transcribe">Transcribe audio</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/voice/lipsync">Make a lip sync</Link>
            </Button>
          </div>
        </div>
      ) : search.status === "searching" ? (
        <ul className={tiles} aria-busy="true" aria-label="Searching">
          {[0, 1, 2].map((i) => (
            <li key={i}>
              <Skeleton className="aspect-[3/4] rounded-lg" />
            </li>
          ))}
        </ul>
      ) : view === "table" ? (
        <CreationsTable entries={shown} />
      ) : (
        <ul className={tiles}>
          {shown.map((entry) => (
            <li key={`${entry.kind}-${entry.id}`} className="grid min-w-0">
              <CreationCard
                entry={entry}
                note={
                  search.status === "done" && search.words.has(entry.id) ? "Exact words" : undefined
                }
              />
            </li>
          ))}
        </ul>
      )}

      {failed ? (
        <Notice tone="error" title="Some creations couldn't load">
          Check your connection and try again.
        </Notice>
      ) : null}
      {!searching && !isEmpty && hasMore ? (
        <div className={cn(actions, "justify-center pt-2 pb-8")}>
          <Button type="button" variant="outline" onClick={more} disabled={loading}>
            {loading ? <Spinner /> : null}Load more
          </Button>
        </div>
      ) : null}
    </section>
  );
}
