"use client";

import { type ImageSummary, type ImagesApi, canRunAgain, sizeName, when } from "@wasifyai/client";
import { Heart, RotateCw, Save, Search, Sparkles } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { extensionOf, fileNameFor, savedText, useSaveCopy } from "../save";
import { RecipeList } from "./ImageWorkspace";

export type ImageLibraryProps = {
  images: ImagesApi;
  /** "Create one" on an empty library. */
  onCreate?: () => void;
  /** "Make it again" on an image that can be (see `canRunAgain`): the app opens Create with it. */
  onRunAgain?: (image: ImageSummary) => void;
  /** Whether "Save a copy" is on offer. */
  canSave?: boolean;
  /** Where an image can be downloaded from (the web app): "Download" is offered when given. */
  downloadHref?: (image: ImageSummary) => string;
  /** The line under the title. */
  subtitle?: string;
  /** Replaces the page's padding (the web app has its own). */
  className?: string;
};

type Filter = "all" | "favourites";

/** Everything the person made, newest first, with search, favourites, save and delete. */
export function ImageLibrary({
  images: api,
  onCreate,
  onRunAgain,
  canSave = false,
  downloadHref,
  subtitle = "Everything you made on this computer.",
  className,
}: ImageLibraryProps) {
  const [items, setItems] = useState<ImageSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState<string | null>(null);
  const [open, setOpen] = useState<ImageSummary | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const saveCopy = useSaveCopy();
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (which: Filter) => {
      try {
        const p = await api.list({ limit: 36, favourites: which === "favourites" });
        setItems(p.images);
        setNext(p.next_before);
        setSearched(null);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "The library could not be read.");
      }
    },
    [api],
  );

  useEffect(() => {
    void load(filter);
  }, [load, filter]);

  function replace(next: ImageSummary) {
    setItems((cur) => {
      if (!cur) return cur;
      const kept = filter === "favourites" && !next.favourite;
      return kept
        ? cur.filter((i) => i.id !== next.id)
        : cur.map((i) => (i.id === next.id ? next : i));
    });
    setOpen((cur) => (cur?.id === next.id ? next : cur));
  }

  async function search(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return load(filter);
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
      const p = await api.list({ limit: 36, before: next, favourites: filter === "favourites" });
      setItems((cur) => [...(cur ?? []), ...p.images]);
      setNext(p.next_before);
    } catch (e) {
      setError(e instanceof Error ? e.message : "More images could not be loaded.");
    }
  }

  async function run<T>(job: () => Promise<T>, fallback: string): Promise<T | undefined> {
    setError(null);
    setMessage(null);
    try {
      return await job();
    } catch (e) {
      setError(e instanceof Error ? e.message : fallback);
      return undefined;
    }
  }

  async function toggleFavourite(img: ImageSummary) {
    const done = await run(() => api.setFavourite(img.id, !img.favourite), "That did not work.");
    if (done) replace(done);
  }

  async function save(img: ImageSummary) {
    const done = await run(
      () =>
        saveCopy({
          name: fileNameFor(img.prompt, extensionOf(img.image_url, "png"), "image"),
          copy: (path) => api.exportCopy(img.id, path),
        }),
      "The image could not be saved.",
    );
    if (done) setMessage(savedText(done));
  }

  async function remove(img: ImageSummary) {
    const ok = await run(async () => {
      await api.remove(img.id);
      return true;
    }, "The image could not be deleted.");
    if (!ok) return;
    setOpen(null);
    setConfirmDelete(false);
    setItems((cur) => (cur ?? []).filter((i) => i.id !== img.id));
  }

  return (
    <div className={cn("mx-auto grid w-full max-w-5xl gap-6 px-8 pt-16 pb-12", className)}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-semibold text-2xl">Your images</h1>
          <p className="text-muted-foreground">{subtitle}</p>
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

      <fieldset className="m-0 flex gap-2 border-0 p-0">
        <legend className="sr-only">Show</legend>
        {(["all", "favourites"] as const).map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={filter === f}
            className={cn(
              "rounded-full border px-3 py-1.5 text-sm",
              filter === f
                ? "border-primary bg-primary/10"
                : "text-muted-foreground hover:bg-accent",
            )}
            onClick={() => {
              setQuery("");
              setFilter(f);
            }}
          >
            {f === "all" ? "All" : "Favourites"}
          </button>
        ))}
      </fieldset>

      {error ? (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      ) : null}
      {message ? <output className="text-sm">{message}</output> : null}

      {items && items.length === 0 ? (
        <div className="grid justify-items-center gap-3 py-16 text-center text-muted-foreground">
          <p>
            {searched
              ? `Nothing matched “${searched}”.`
              : filter === "favourites"
                ? "No favourites yet. Tap the heart on an image to keep it here."
                : "No images yet."}
          </p>
          {searched ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setQuery("");
                void load(filter);
              }}
            >
              Show everything
            </Button>
          ) : onCreate && filter === "all" ? (
            <Button type="button" onClick={onCreate}>
              <Sparkles className="size-4" /> Create one
            </Button>
          ) : null}
        </div>
      ) : null}

      <ul
        className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-3"
        aria-label="Images"
      >
        {(items ?? []).map((img) => (
          <li key={img.id} className="relative">
            <button
              type="button"
              aria-label={`Open: ${img.prompt}`}
              className="block w-full overflow-hidden rounded-lg border outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => {
                setOpen(img);
                setConfirmDelete(false);
                setMessage(null);
              }}
            >
              <img src={img.thumb_url} alt="" className="aspect-square w-full object-cover" />
            </button>
            {img.favourite ? (
              <Heart
                className="pointer-events-none absolute end-2 top-2 size-4 fill-current text-white drop-shadow"
                aria-label="Favourite"
              />
            ) : null}
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
              className="mx-auto max-h-[55vh] max-w-full rounded-lg object-contain"
            />
            <p>{open.prompt}</p>
            <p className="text-muted-foreground text-sm">
              {open.mode === "image" ? "Edit of a picture" : "From text"} · {open.width}×
              {open.height} ({sizeName(open.width, open.height)}) · {when(open.created_at)}
              {open.recipe ? ` · seed ${open.recipe.seed}` : ""}
            </p>
            <RecipeList image={open} />
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                aria-pressed={open.favourite}
                onClick={() => void toggleFavourite(open)}
              >
                <Heart className={cn("size-4", open.favourite && "fill-current")} />
                {open.favourite ? "Favourite" : "Add to favourites"}
              </Button>
              {canSave ? (
                <Button type="button" variant="outline" onClick={() => void save(open)}>
                  <Save className="size-4" /> Save a copy
                </Button>
              ) : null}
              {downloadHref ? (
                <Button asChild variant="outline">
                  <a href={downloadHref(open)} download>
                    <Save className="size-4" /> Download
                  </a>
                </Button>
              ) : null}
              {onRunAgain && canRunAgain(open) ? (
                <Button type="button" variant="outline" onClick={() => onRunAgain(open)}>
                  <RotateCw className="size-4" /> Make it again
                </Button>
              ) : null}
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
            {message ? <output className="text-sm">{message}</output> : null}
          </div>
        </dialog>
      ) : null}
    </div>
  );
}
