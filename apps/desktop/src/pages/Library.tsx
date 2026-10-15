// SPDX-License-Identifier: AGPL-3.0-only
import { Button, Notice, cn } from "@wasifyai/ui";
import { Search, Sparkles } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  type ImageSummary,
  deleteImage,
  listImages,
  searchImages,
  sizeName,
  when,
} from "../images";
import type { Route } from "../router";

/** Everything made on this computer, newest first, with a search over what the images were made from. */
export function LibraryPage({ go }: { go: (r: Route) => void }) {
  const [images, setImages] = useState<ImageSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState<string | null>(null);
  const [open, setOpen] = useState<ImageSummary | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const p = await listImages(36);
      setImages(p.images);
      setNext(p.next_before);
      setSearched(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The library could not be read.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function search(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return load();
    setError(null);
    try {
      setImages(await searchImages(q));
      setNext(null);
      setSearched(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The search did not work.");
    }
  }

  async function more() {
    if (!next) return;
    const p = await listImages(36, next);
    setImages((cur) => [...(cur ?? []), ...p.images]);
    setNext(p.next_before);
  }

  async function remove(img: ImageSummary) {
    try {
      await deleteImage(img.id);
      setOpen(null);
      setConfirmDelete(false);
      setImages((cur) => (cur ?? []).filter((i) => i.id !== img.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The image could not be deleted.");
    }
  }

  return (
    <div className="mx-auto grid w-full max-w-5xl gap-6 px-8 pt-16 pb-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-semibold text-2xl">Library</h1>
          <p className="text-muted-foreground">Everything you made on this computer.</p>
        </div>
        <form className="flex items-center gap-2" onSubmit={search}>
          <label className="relative">
            <span className="sr-only">Search your images</span>
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

      {images && images.length === 0 ? (
        <div className="grid justify-items-center gap-3 py-16 text-center text-muted-foreground">
          <p>{searched ? `Nothing matched “${searched}”.` : "No images yet."}</p>
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
          ) : (
            <Button type="button" onClick={() => go("create")}>
              <Sparkles className="size-4" /> Create one
            </Button>
          )}
        </div>
      ) : null}

      <ul
        className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-3"
        aria-label="Images"
      >
        {(images ?? []).map((img) => (
          <li key={img.id}>
            <button
              type="button"
              aria-label={`Open: ${img.prompt}`}
              className="block w-full overflow-hidden rounded-lg border outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => {
                setOpen(img);
                setConfirmDelete(false);
              }}
            >
              <img src={img.thumb_url} alt="" className="aspect-square w-full object-cover" />
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
          aria-label="Image"
          className="fixed inset-0 z-50 m-0 grid h-full w-full max-w-none place-items-center bg-background/80 p-6 backdrop-blur-sm"
        >
          <div className="grid max-h-full w-full max-w-4xl gap-4 overflow-auto rounded-2xl border bg-card p-5 shadow-card">
            <img
              src={open.image_url}
              alt={open.prompt}
              className="mx-auto max-h-[60vh] max-w-full rounded-lg object-contain"
            />
            <p>{open.prompt}</p>
            <p className="text-muted-foreground text-sm">
              {open.mode === "image" ? "Edit of a picture" : "From text"} · {open.width}×
              {open.height} ({sizeName(open.width, open.height)}) · {when(open.created_at)}
            </p>
            <div className={cn("flex flex-wrap gap-2")}>
              {confirmDelete ? (
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
          </div>
        </dialog>
      ) : null}
    </div>
  );
}
