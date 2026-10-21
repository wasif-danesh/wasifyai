"use client";

import { type VideoSummary, type VideosApi, clipLength, when } from "@wasifyai/client";
import { Save, Search, Sparkles } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { Spinner } from "../components/spinner";
import { extensionOf, fileNameFor, savedText, useSaveCopy } from "../save";

export type VideoLibraryProps = {
  videos: VideosApi;
  /** "Make one" on an empty library. */
  onCreate?: () => void;
  /** Whether "Save a copy" is on offer. */
  canSave?: boolean;
  /** Where a clip can be downloaded from (the web app): "Download" is offered when given. */
  downloadHref?: (video: VideoSummary) => string;
  /** The line under the title. */
  subtitle?: string;
  /** Replaces the page's padding (the web app has its own). */
  className?: string;
  /** How often to look again while a clip is being made (milliseconds). */
  pollMs?: number;
};

/** Everything the person made, newest first, with search, save and delete; clips being made show up too. */
export function VideoLibrary({
  videos: api,
  onCreate,
  canSave = false,
  downloadHref,
  subtitle = "Every clip you made on this computer.",
  className,
  pollMs = 5000,
}: VideoLibraryProps) {
  const [items, setItems] = useState<VideoSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const saveCopy = useSaveCopy();
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState<string | null>(null);
  const [open, setOpen] = useState<VideoSummary | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const p = await api.list({ limit: 24 });
      setItems(p.videos);
      setNext(p.next_before);
      setSearched(null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Your videos could not be read.");
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  // a clip being made turns into a finished one by itself
  const making = (items ?? []).some((v) => v.status === "working");
  useEffect(() => {
    if (!making || searched) return;
    const id = setInterval(() => void load(), pollMs);
    return () => clearInterval(id);
  }, [making, searched, load, pollMs]);

  async function search(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return load();
    setError(null);
    try {
      setItems(await api.search(q));
      setNext(null);
      setSearched(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The search did not work.");
    }
  }

  async function more() {
    if (!next) return;
    try {
      const p = await api.list({ limit: 24, before: next });
      setItems((cur) => [...(cur ?? []), ...p.videos]);
      setNext(p.next_before);
    } catch (e) {
      setError(e instanceof Error ? e.message : "More videos could not be loaded.");
    }
  }

  async function save(video: VideoSummary) {
    setError(null);
    setMessage(null);
    try {
      const done = await saveCopy({
        name: fileNameFor(video.prompt, extensionOf(video.video_url ?? "", "mp4"), "video"),
        copy: (path) => api.exportCopy(video.id, path),
      });
      if (done) setMessage(savedText(done));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The video could not be saved.");
    }
  }

  async function remove(video: VideoSummary) {
    setError(null);
    try {
      await api.remove(video.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The video could not be deleted.");
      return;
    }
    setOpen(null);
    setConfirmDelete(false);
    setItems((cur) => (cur ?? []).filter((v) => v.id !== video.id));
  }

  return (
    <div className={cn("mx-auto grid w-full max-w-5xl gap-6 px-8 pt-16 pb-12", className)}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-semibold text-2xl">Your videos</h1>
          <p className="text-muted-foreground">{subtitle}</p>
        </div>
        <form className="flex items-center gap-2" onSubmit={search}>
          <label className="relative">
            <span className="sr-only">Search your videos</span>
            <Search className="-translate-y-1/2 absolute start-3 top-1/2 size-4 text-muted-foreground" />
            <input
              type="search"
              className="h-10 w-64 rounded-full border border-input bg-transparent ps-9 pe-4 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              placeholder="Search by words or meaning"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <Button type="submit" size="sm">
            Search
          </Button>
        </form>
      </div>

      {error ? (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      ) : null}
      {message ? <output className="text-sm">{message}</output> : null}

      {items && items.length === 0 ? (
        <div className="grid justify-items-center gap-3 py-16 text-center text-muted-foreground">
          <p>{searched ? `Nothing matched “${searched}”.` : "No videos yet."}</p>
          {searched ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setQuery("");
                void load();
              }}
            >
              Show everything
            </Button>
          ) : onCreate ? (
            <Button type="button" onClick={onCreate}>
              <Sparkles className="size-4" /> Make one
            </Button>
          ) : null}
        </div>
      ) : null}

      <ul
        className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3"
        aria-label="Videos"
      >
        {(items ?? []).map((v) => (
          <li key={v.id}>
            <button
              type="button"
              aria-label={`Open: ${v.prompt}`}
              className="grid w-full gap-2 overflow-hidden rounded-lg border p-0 text-start outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => {
                setOpen(v);
                setConfirmDelete(false);
                setMessage(null);
              }}
            >
              {v.status === "done" && v.poster_url ? (
                <img src={v.poster_url} alt="" className="aspect-[3/2] w-full object-cover" />
              ) : (
                <div className="grid aspect-[3/2] w-full place-items-center bg-muted text-muted-foreground text-sm">
                  {v.status === "working" ? (
                    <span className="flex items-center gap-2">
                      <Spinner /> Being made
                    </span>
                  ) : (
                    "Not made"
                  )}
                </div>
              )}
              <span className="line-clamp-2 px-3 pb-2 text-sm">{v.prompt}</span>
            </button>
          </li>
        ))}
      </ul>

      {next ? (
        <div className="justify-self-center">
          <Button type="button" variant="outline" onClick={() => void more()}>
            Show more
          </Button>
        </div>
      ) : null}

      {open ? (
        <dialog
          open
          aria-label="Video"
          className="fixed inset-0 z-50 m-0 grid h-full w-full max-w-none place-items-center bg-background/80 p-6 backdrop-blur-sm"
        >
          <div className="grid max-h-full w-full max-w-4xl gap-4 overflow-auto rounded-2xl border bg-card p-5 shadow-card">
            {open.status === "done" && open.video_url ? (
              // biome-ignore lint/a11y/useMediaCaption: generated clips have no speech to caption
              <video
                className="mx-auto max-h-[55vh] max-w-full rounded-lg bg-black"
                controls
                playsInline
                preload="metadata"
                poster={open.poster_url ?? undefined}
                src={open.video_url}
              />
            ) : open.status === "working" ? (
              <p className="flex items-center gap-2 text-muted-foreground">
                <Spinner /> This clip is still being made. It will appear here when it is ready.
              </p>
            ) : (
              <Notice tone="error" title="This clip could not be made">
                {open.error ?? "Something went wrong."}
              </Notice>
            )}
            <p>{open.prompt}</p>
            <p className="text-muted-foreground text-sm">
              {{
                image: "From a picture",
                extend: "Carried on",
                import: "Added from your computer",
                text: "From text",
              }[open.mode] ?? "From text"}{" "}
              · {clipLength(open.seconds)}
              {open.width && open.height ? ` · ${open.width}×${open.height}` : ""} ·{" "}
              {when(open.created_at)}
            </p>
            <div className="flex flex-wrap gap-2">
              {canSave && open.status === "done" ? (
                <Button type="button" variant="outline" onClick={() => void save(open)}>
                  <Save className="size-4" /> Save a copy
                </Button>
              ) : null}
              {downloadHref && open.status === "done" ? (
                <Button asChild variant="outline">
                  <a href={downloadHref(open)} download>
                    <Save className="size-4" /> Download
                  </a>
                </Button>
              ) : null}
              {open.status === "working" ? null : confirmDelete ? (
                <>
                  <Button type="button" variant="destructive" onClick={() => void remove(open)}>
                    Yes, delete it
                  </Button>
                  <Button type="button" variant="outline" onClick={() => setConfirmDelete(false)}>
                    Keep it
                  </Button>
                </>
              ) : (
                <Button type="button" variant="outline" onClick={() => setConfirmDelete(true)}>
                  Delete
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                className="ms-auto"
                onClick={() => setOpen(null)}
              >
                Close
              </Button>
            </div>
            {message ? <output className="text-sm">{message}</output> : null}
          </div>
        </dialog>
      ) : null}
    </div>
  );
}
