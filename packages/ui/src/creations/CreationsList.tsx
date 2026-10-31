"use client";

import type {
  CreationsApi,
  ImagePage,
  LipSyncCard,
  Others,
  SongCard,
  SpeechCard,
  TranscriptCard,
  VideoPage,
} from "@wasifyai/client";
import { AudioLines, CheckSquare, LayoutGrid, Save, Table2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { ConfirmDialog } from "../components/dialog";
import { Input } from "../components/input";
import { Label } from "../components/label";
import { Notice } from "../components/notice";
import { Select } from "../components/select";
import { Skeleton } from "../components/skeleton";
import { Spinner } from "../components/spinner";
import { ToggleGroup, ToggleGroupItem } from "../components/toggle-group";
import { fileNameFor, savedText, useSaveCopy } from "../save";
import { actions, empty, hint, panel } from "../styles";
import { CreationCard } from "./CreationCard";
import { CreationDetail, apiKindOf, fileOf } from "./CreationDetail";
import { CreationsTable } from "./CreationsTable";
import { NavLink } from "./NavLink";
import {
  type CreationsNav,
  type Entry,
  FILTER_KIND,
  type Filter,
  KIND_LABEL,
  toRow,
} from "./model";
import { useCreationSearch } from "./use-creation-search";

const PAGE = 12;
const tiles =
  "m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,13rem),1fr))] items-stretch gap-4 p-0";
const FILTERS: { value: Filter; label: string; whenAny?: boolean }[] = [
  { value: "all", label: "All" },
  { value: "images", label: "Pictures" },
  { value: "videos", label: "Videos" },
  { value: "songs", label: "Music" },
  { value: "speeches", label: "Speech" },
  { value: "transcripts", label: "Transcripts" },
  { value: "lipsyncs", label: "Lip syncs" },
  // the tools' own kinds show up once there is one
  { value: "models3d", label: "3D models", whenAny: true },
  { value: "compositions", label: "Motion graphics", whenAny: true },
  { value: "creativeProjects", label: "Creative Studio", whenAny: true },
  { value: "notebooks", label: "Notebooks", whenAny: true },
  { value: "taught", label: "Taught models", whenAny: true },
];

type Sort = "newest" | "oldest" | "name";
const SORTS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "name", label: "A to Z" },
];

const keyOf = (e: Entry) => `${e.kind}:${e.id}`;

export function CreationsList({
  api,
  nav,
  songs = [],
  images: imagePage,
  videos: videoPage = null,
  speeches = [],
  transcripts = [],
  lipsyncs = [],
  others,
  initialFilter = "all",
  initialOpen,
}: {
  api: CreationsApi;
  nav: CreationsNav;
  /** the voice product's lists: the latest of each, with no further pages */
  songs?: SongCard[];
  images: ImagePage | null;
  videos?: VideoPage | null;
  speeches?: SpeechCard[];
  transcripts?: TranscriptCard[];
  lipsyncs?: LipSyncCard[];
  /** 3D models, motion graphics, notebooks and taught models */
  others?: Others;
  initialFilter?: Filter;
  /** an entry to open in the detail view once, as the Library opens */
  initialOpen?: { kind: string; id: string } | null;
}) {
  const [images, setImages] = useState(imagePage?.images ?? []);
  const [videos, setVideos] = useState(videoPage?.videos ?? []);
  const [imageNext, setImageNext] = useState(imagePage?.next_before ?? null);
  const [videoNext, setVideoNext] = useState(videoPage?.next_before ?? null);
  const [filter, setFilter] = useState<Filter>(initialFilter);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [sort, setSort] = useState<Sort>("newest");
  // what was deleted here: taken off the lists without reading them again
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [opened, setOpened] = useState<Entry | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [askDelete, setAskDelete] = useState(false);
  const [bulkNote, setBulkNote] = useState<string | null>(null);
  const [bulkProblem, setBulkProblem] = useState<string | null>(null);
  const saveCopy = useSaveCopy();

  const everything = useMemo<Entry[]>(() => {
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
      ...(others?.models3d ?? []).map((model3d) => ({
        kind: "model3d" as const,
        id: model3d.id,
        createdAt: model3d.created_at,
        model3d,
      })),
      ...(others?.compositions ?? []).map((composition) => ({
        kind: "composition" as const,
        id: composition.id,
        createdAt: composition.updated_at || composition.created_at,
        composition,
      })),
      ...(others?.creativeProjects ?? []).map((project) => ({
        kind: "creative_project" as const,
        id: project.id,
        createdAt: project.updated_at || project.created_at,
        project,
      })),
      ...(others?.notebooks ?? []).map((notebook) => ({
        kind: "notebook" as const,
        id: notebook.id,
        createdAt: notebook.updated_at || notebook.created_at,
        notebook,
      })),
      ...(others?.taught ?? []).map((taught) => ({
        kind: "taught" as const,
        id: taught.id,
        createdAt: taught.created_at,
        taught,
      })),
    ];
    return all.filter((entry) => !gone.has(keyOf(entry)));
  }, [images, lipsyncs, songs, speeches, transcripts, videos, others, gone]);

  const entries = useMemo<Entry[]>(() => {
    const wanted = FILTER_KIND[filter];
    const shown = everything.filter((entry) => wanted === null || entry.kind === wanted);
    if (sort === "name") {
      const title = (e: Entry) => toRow(e).title;
      return shown.sort((a, b) => title(a).localeCompare(title(b)));
    }
    const sign = sort === "oldest" ? 1 : -1;
    return shown.sort((a, b) => sign * (Date.parse(a.createdAt) - Date.parse(b.createdAt)));
  }, [everything, filter, sort]);

  /** Load the next page of one kind. Returns true when it failed. */
  async function page<T>(load: () => Promise<T>, apply: (p: T) => void): Promise<boolean> {
    try {
      apply(await load());
      return false;
    } catch {
      return true;
    }
  }

  async function more() {
    if (loading) return;
    setLoading(true);
    setFailed(false);
    const jobs: Promise<boolean>[] = [];
    if (imageNext && (filter === "all" || filter === "images")) {
      jobs.push(
        page<ImagePage>(
          () => api.moreImages(imageNext, PAGE),
          (p) => {
            setImages((cur) => [...cur, ...p.images]);
            setImageNext(p.next_before ?? null);
          },
        ),
      );
    }
    if (videoNext && (filter === "all" || filter === "videos")) {
      jobs.push(
        page<VideoPage>(
          () => api.moreVideos(videoNext, PAGE),
          (p) => {
            setVideos((cur) => [...cur, ...p.videos]);
            setVideoNext(p.next_before ?? null);
          },
        ),
      );
    }
    const results = await Promise.all(jobs);
    setFailed(results.some(Boolean));
    setLoading(false);
  }

  const counts = Object.fromEntries(
    FILTERS.map(({ value }) => {
      const kind = FILTER_KIND[value];
      return [value, everything.filter((e) => kind === null || e.kind === kind).length];
    }),
  ) as Record<Filter, number>;
  // a kind with more pages says so: the count is what is loaded so far
  const more_ = { images: Boolean(imageNext), videos: Boolean(videoNext) };
  const countText = (f: Filter) =>
    `${counts[f]}${(f === "images" && more_.images) || (f === "videos" && more_.videos) || (f === "all" && (more_.images || more_.videos)) ? "+" : ""}`;

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

  const open = useCallback((entry: Entry) => setOpened(entry), []);
  // the home's Recent opens one entry here
  const openedFirst = useRef(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: once, when the entries are there
  useEffect(() => {
    if (openedFirst.current || !initialOpen) return;
    const found = everything.find((e) => e.kind === initialOpen.kind && e.id === initialOpen.id);
    if (found) {
      openedFirst.current = true;
      setOpened(found);
    }
  }, [everything]);
  const toggle = (entry: Entry) =>
    setSelected((cur) => {
      const next = new Set(cur);
      const k = keyOf(entry);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  const chosen = everything.filter((e) => selected.has(keyOf(e)));
  function stopSelecting() {
    setSelecting(false);
    setSelected(new Set());
  }

  async function saveChosen() {
    setBulkNote(null);
    setBulkProblem(null);
    let n = 0;
    for (const entry of chosen) {
      const file = fileOf(entry);
      if (!file) continue;
      try {
        const out = await saveCopy({
          name: fileNameFor(file.name, file.ext, KIND_LABEL[entry.kind].toLowerCase()),
          blob: async () => (await fetch(file.url)).blob(),
        });
        if (out) {
          n += 1;
          if (chosen.length === 1) setBulkNote(savedText(out));
        }
      } catch (e) {
        setBulkProblem(e instanceof Error ? e.message : "One of them could not be saved.");
      }
    }
    if (chosen.length > 1) setBulkNote(`${n} saved.`);
  }

  async function deleteChosen() {
    setAskDelete(false);
    setBulkProblem(null);
    const done = new Set<string>();
    for (const entry of chosen) {
      try {
        await api.remove(apiKindOf(entry), entry.id);
        done.add(keyOf(entry));
      } catch {
        setBulkProblem("Some of them could not be deleted. They are still chosen.");
      }
    }
    setGone((cur) => new Set([...cur, ...done]));
    setSelected((cur) => new Set([...cur].filter((k) => !done.has(k))));
    setBulkNote(`${done.size} deleted.`);
  }

  const [query, setQuery] = useState("");
  const searchId = useId();
  const search = useCreationSearch(api, query, filter);
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

      <div className="flex flex-wrap items-center justify-between gap-3 pt-1 pb-2">
        <fieldset className="m-0 flex min-w-0 max-w-full flex-wrap gap-1 rounded-3xl border bg-surface p-[0.3rem]">
          <legend className="sr-only">Filter creations</legend>
          {FILTERS.filter(
            ({ value, whenAny }) => !whenAny || counts[value] > 0 || filter === value,
          ).map(({ value, label }) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
              className="inline-flex items-center gap-[0.45rem] rounded-full border-0 bg-transparent px-[0.85rem] py-[0.55rem] text-ui font-semibold text-muted-foreground transition-colors hover:text-foreground aria-pressed:bg-accent aria-pressed:text-foreground max-[520px]:px-[0.7rem]"
            >
              {label} <span className="text-ui-sm">{countText(value)}</span>
            </button>
          ))}
        </fieldset>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            aria-label="Sort"
            className="h-9 w-40"
            value={sort}
            onValueChange={(v) => setSort(v as Sort)}
            options={SORTS}
          />
          <Button
            type="button"
            size="sm"
            variant={selecting ? "secondary" : "outline"}
            aria-pressed={selecting}
            onClick={() => (selecting ? stopSelecting() : setSelecting(true))}
          >
            <CheckSquare aria-hidden="true" /> {selecting ? "Done" : "Select"}
          </Button>
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
        </div>
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

      {selecting ? (
        <div
          role="toolbar"
          aria-label="What to do with the chosen ones"
          className="flex flex-wrap items-center gap-2 rounded-md border bg-surface px-3 py-2"
        >
          <span className="me-auto text-sm">
            {chosen.length === 0 ? "Choose the ones to save or delete." : `${chosen.length} chosen`}
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!chosen.some((e) => fileOf(e))}
            onClick={() => void saveChosen()}
          >
            <Save aria-hidden="true" /> Save
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="text-destructive"
            disabled={chosen.length === 0}
            onClick={() => setAskDelete(true)}
          >
            <Trash2 aria-hidden="true" /> Delete
          </Button>
        </div>
      ) : null}
      {bulkNote ? <output className="text-sm">{bulkNote}</output> : null}
      {bulkProblem ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {bulkProblem}
        </p>
      ) : null}

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
          {filter === "all" || filter === "songs" ? (
            <AudioLines className="size-6" aria-hidden="true" />
          ) : null}
          <h2 className="text-step-1 font-semibold">
            {filter === "all"
              ? "Your creative space is ready"
              : `No ${filter === "speeches" ? "speech" : filter === "songs" ? "music" : filter} yet`}
          </h2>
          <p>Make something new and it will appear here.</p>
          <div className={actions}>
            <Button asChild>
              <NavLink nav={nav} to="music">
                Create music
              </NavLink>
            </Button>
            <Button asChild variant="outline">
              <NavLink nav={nav} to="image">
                Make an image
              </NavLink>
            </Button>
            <Button asChild variant="outline">
              <NavLink nav={nav} to="video">
                Make a video
              </NavLink>
            </Button>
            <Button asChild variant="outline">
              <NavLink nav={nav} to="speech">
                Create speech
              </NavLink>
            </Button>
            <Button asChild variant="outline">
              <NavLink nav={nav} to="transcribe">
                Transcribe audio
              </NavLink>
            </Button>
            <Button asChild variant="outline">
              <NavLink nav={nav} to="lipsync">
                Make a lip sync
              </NavLink>
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
        <CreationsTable entries={shown} nav={nav} onOpen={selecting ? toggle : open} />
      ) : (
        <ul className={tiles}>
          {shown.map((entry) => (
            <li key={`${entry.kind}-${entry.id}`} className="relative grid min-w-0">
              <CreationCard
                entry={entry}
                nav={nav}
                onOpen={selecting ? toggle : open}
                note={
                  search.status === "done" && search.words.has(entry.id) ? "Exact words" : undefined
                }
              />
              {selecting ? (
                <Checkbox
                  className="absolute end-3 top-3 rounded-md bg-surface/90 px-1.5 py-1"
                  label={`Choose ${toRow(entry).title.slice(0, 60)}`}
                  checked={selected.has(keyOf(entry))}
                  onCheckedChange={() => toggle(entry)}
                />
              ) : null}
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
      {opened ? (
        <CreationDetail
          key={keyOf(opened)}
          entry={opened}
          api={api}
          nav={nav}
          onOpen={open}
          onClose={() => setOpened(null)}
          onRemoved={(entry) => {
            setGone((cur) => new Set([...cur, keyOf(entry)]));
            setOpened(null);
          }}
        />
      ) : null}
      {askDelete ? (
        <ConfirmDialog
          title={chosen.length === 1 ? "Delete this one?" : `Delete these ${chosen.length}?`}
          message="They are deleted for good."
          onConfirm={() => void deleteChosen()}
          onCancel={() => setAskDelete(false)}
        />
      ) : null}
    </section>
  );
}
