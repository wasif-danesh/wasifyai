"use client";

import { type NotebookSummary, when } from "@wasifyai/client";
import { BookOpen, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog, NameDialog } from "../components/dialog";
import { useNotebookPlace } from "./place";

export type NotebookListProps = {
  notebooks: NotebookSummary[];
  loading?: boolean;
  error?: string | null;
  onOpen: (n: NotebookSummary) => void;
  onCreate: () => void;
  /** called with the new name, once the person has typed one */
  onRename: (n: NotebookSummary, name: string) => void;
  /** called once the person has said yes to deleting it */
  onRemove: (n: NotebookSummary) => void;
  /** Find notebooks by what is in them (My creations search). */
  onFind?: (query: string) => Promise<string[]>;
  /** Replaces the page's padding (the web app has its own). */
  className?: string;
};

function lowerWhen(iso: string): string {
  const w = when(iso);
  return w === "Today" || w === "Yesterday" ? w.toLowerCase() : `on ${w}`;
}

function counts(n: NotebookSummary): string {
  if (n.sources === 0) return "No sources yet";
  const parts = [`${n.sources} source${n.sources === 1 ? "" : "s"}`];
  if (n.reading) parts.push(`${n.reading} being read`);
  if (n.failed) parts.push(`${n.failed} could not be read`);
  return parts.join(", ");
}

/** The notebooks of this computer as cards, with a search over their titles and sources. */
export function NotebookList({
  notebooks,
  loading,
  error,
  onOpen,
  onCreate,
  onRename,
  onRemove,
  onFind,
  className,
}: NotebookListProps) {
  const hosted = useNotebookPlace() === "hosted";
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Set<string>>(new Set());
  // the app window cannot show window.prompt or window.confirm: the app's own dialogs ask
  const [renaming, setRenaming] = useState<NotebookSummary | null>(null);
  const [removing, setRemoving] = useState<NotebookSummary | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2 || !onFind) {
      setFound(new Set());
      return;
    }
    let gone = false;
    const t = setTimeout(() => {
      onFind(q)
        .then((ids) => !gone && setFound(new Set(ids)))
        .catch(() => !gone && setFound(new Set()));
    }, 250);
    return () => {
      gone = true;
      clearTimeout(t);
    };
  }, [query, onFind]);

  const q = query.trim().toLowerCase();
  const shown = q
    ? notebooks.filter((n) => n.title.toLowerCase().includes(q) || found.has(n.id))
    : notebooks;

  return (
    <div
      className={cn(
        "mx-auto grid w-full min-w-0 max-w-5xl grid-cols-[minmax(0,1fr)] gap-6 px-8 py-8",
        className,
      )}
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-medium text-3xl tracking-tight">Notebooks</h1>
        <div className="flex items-center gap-2">
          {notebooks.length > 3 ? (
            <input
              type="search"
              aria-label="Find a notebook"
              placeholder="Find a notebook"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-10 w-56 rounded-md border bg-background px-3"
            />
          ) : null}
          <Button type="button" onClick={onCreate}>
            <Plus /> New notebook
          </Button>
        </div>
      </header>

      {error ? (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      ) : null}

      {!loading && notebooks.length === 0 ? (
        <div className="grid justify-items-center gap-4 rounded-3xl border border-dashed px-8 py-16 text-center">
          <BookOpen className="size-10 text-muted-foreground" aria-hidden="true" />
          <h2 className="font-medium text-xl">Start your first notebook</h2>
          <p className="max-w-md text-muted-foreground">
            Add documents and ask questions about them. Answers cite the passages they came from,
            and {hosted ? "your documents are private to you" : "everything stays on this computer"}
            . PDF, Word, PowerPoint, Excel, text, Markdown, HTML and pictures of text can be added.
          </p>
          <Button type="button" onClick={onCreate}>
            <Plus /> New notebook
          </Button>
        </div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((n) => (
            <li key={n.id} className="group relative">
              <button
                type="button"
                onClick={() => onOpen(n)}
                className="grid h-full w-full gap-1 rounded-2xl border bg-card p-5 text-start shadow-card transition-colors hover:bg-accent"
              >
                <span className="line-clamp-2 font-medium text-lg">{n.title}</span>
                <span className="text-muted-foreground text-sm">{counts(n)}</span>
                <span className="text-muted-foreground text-xs">
                  {n.opened_at
                    ? `Opened ${lowerWhen(n.opened_at)}`
                    : `Made ${lowerWhen(n.created_at)}`}
                </span>
              </button>
              <span className="absolute end-2 top-2 hidden gap-1 group-focus-within:flex group-hover:flex">
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  aria-label={`Rename ${n.title}`}
                  onClick={() => setRenaming(n)}
                >
                  Rename
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Delete ${n.title}`}
                  onClick={() => setRemoving(n)}
                >
                  <Trash2 />
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {renaming ? (
        <NameDialog
          title="Rename notebook"
          label="Name"
          initial={renaming.title}
          onSubmit={(name) => {
            setRenaming(null);
            onRename(renaming, name);
          }}
          onCancel={() => setRenaming(null)}
        />
      ) : null}
      {removing ? (
        <ConfirmDialog
          title={`Delete “${removing.title}”?`}
          message={`${
            removing.sources
              ? `Its ${removing.sources} source${removing.sources === 1 ? "" : "s"} will be deleted too. `
              : ""
          }This cannot be undone.`}
          onConfirm={() => {
            setRemoving(null);
            onRemove(removing);
          }}
          onCancel={() => setRemoving(null)}
        />
      ) : null}
    </div>
  );
}
