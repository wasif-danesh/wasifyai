"use client";

import type { NotebookFolder, NotebookSource } from "@wasifyai/client";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder as FolderIcon,
  FolderPlus,
  Loader2,
  NotebookPen,
  Pencil,
  Plus,
  RotateCw,
  Trash2,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { sourcesUnder, tickOf, toggle } from "./scope";
import { reading } from "./use-notebook-sources";

export type SourcesPaneProps = {
  sources: NotebookSource[];
  folders: NotebookFolder[];
  unticked: Set<string>;
  onUnticked: (next: Set<string>) => void;
  onOpen: (source: NotebookSource) => void;
  onAdd: () => void;
  onNewFolder: (name: string) => void;
  onRename: (source: NotebookSource, title: string) => void;
  onRemove: (source: NotebookSource) => void;
  onRetry: (source: NotebookSource) => void;
  onCancel: (source: NotebookSource) => void;
  onMove: (source: NotebookSource, folderId: string | null) => void;
  onRenameFolder: (folder: NotebookFolder, name: string) => void;
  onRemoveFolder: (folder: NotebookFolder) => void;
  /** The source whose passage is open, to mark its row */
  openId?: string | null;
};

function Tick({
  state,
  label,
  onChange,
}: {
  state: "all" | "some" | "none";
  label: string;
  onChange: () => void;
}) {
  return (
    <input
      type="checkbox"
      aria-label={label}
      checked={state === "all"}
      ref={(el) => {
        if (el) el.indeterminate = state === "some";
      }}
      onChange={onChange}
      className="size-4 shrink-0 accent-[var(--accent)]"
    />
  );
}

function status(s: NotebookSource) {
  if (s.status === "failed")
    return (
      <span className="text-destructive text-xs" title={s.error ?? undefined}>
        Could not be read
      </span>
    );
  if (s.status === "cancelled")
    return <span className="text-muted-foreground text-xs">Stopped</span>;
  if (reading(s))
    return (
      <span className="flex items-center gap-1 text-muted-foreground text-xs">
        <Loader2 className="size-3 animate-spin" aria-hidden="true" />
        {s.status === "pending" ? "Waiting" : "Reading…"}
      </span>
    );
  return null;
}

/** The sources of a notebook as a tree with ticks: what a question is asked of. */
export function SourcesPane(props: SourcesPaneProps) {
  const { sources, folders, unticked, onUnticked } = props;
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [moving, setMoving] = useState<string | null>(null);
  const [naming, setNaming] = useState(false);
  const [folderName, setFolderName] = useState("");

  const q = filter.trim().toLowerCase();
  const shown = useMemo(
    () => (q ? sources.filter((s) => s.title.toLowerCase().includes(q)) : sources),
    [sources, q],
  );
  const top = shown.filter((s) => s.folder_id === null);
  const roots = folders.filter((f) => f.parent_id === null);

  function row(s: NotebookSource, depth: number) {
    const tick = unticked.has(s.id) ? "none" : "all";
    return (
      <li key={s.id} className="group" style={{ paddingInlineStart: `${depth * 14}px` }}>
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-accent",
            props.openId === s.id && "bg-accent",
          )}
        >
          <Tick
            state={s.status === "ready" || tick === "none" ? tick : "all"}
            label={`Use ${s.title}`}
            onChange={() => onUnticked(toggle([s.id], unticked))}
          />
          {s.kind === "note" ? (
            <NotebookPen className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          ) : (
            <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          )}
          <button
            type="button"
            className="min-w-0 flex-1 truncate text-start text-sm"
            title={s.title}
            onClick={() => props.onOpen(s)}
          >
            {s.title}
          </button>
          {status(s)}
          <span className="hidden items-center group-focus-within:flex group-hover:flex">
            {s.status === "failed" || s.status === "cancelled" ? (
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`Read ${s.title} again`}
                onClick={() => props.onRetry(s)}
              >
                <RotateCw />
              </Button>
            ) : null}
            {reading(s) ? (
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`Stop reading ${s.title}`}
                onClick={() => props.onCancel(s)}
              >
                <X />
              </Button>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={`Rename ${s.title}`}
              onClick={() => {
                const next = window.prompt("Name this source", s.title)?.trim();
                if (next && next !== s.title) props.onRename(s, next);
              }}
            >
              <Pencil />
            </Button>
            {folders.length > 0 ? (
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`Move ${s.title}`}
                onClick={() => setMoving(moving === s.id ? null : s.id)}
              >
                <FolderIcon />
              </Button>
            ) : null}
            {!(s.status === "processing") ? (
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`Remove ${s.title}`}
                onClick={() => {
                  if (window.confirm(`Remove “${s.title}” from this notebook?`)) props.onRemove(s);
                }}
              >
                <Trash2 />
              </Button>
            ) : null}
          </span>
        </div>
        {s.status === "failed" && s.error ? (
          <p className="px-8 pb-1 text-muted-foreground text-xs">{s.error}</p>
        ) : null}
        {moving === s.id ? (
          <label className="flex items-center gap-2 px-8 pb-2 text-sm">
            Move to
            <select
              className="h-8 rounded-md border bg-background px-2"
              value={s.folder_id ?? ""}
              onChange={(e) => {
                props.onMove(s, e.target.value || null);
                setMoving(null);
              }}
            >
              <option value="">Top level</option>
              {folders.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </li>
    );
  }

  function folder(f: NotebookFolder, depth: number): React.ReactNode {
    const under = sourcesUnder(folders, sources, f.id);
    const tick = tickOf(
      under.map((s) => s.id),
      unticked,
    );
    const isOpen = open.has(f.id) || q.length > 0;
    const kids = folders.filter((x) => x.parent_id === f.id);
    const own = shown.filter((s) => s.folder_id === f.id);
    if (q && own.length === 0 && kids.length === 0) return null;
    return (
      <li key={f.id} className="group" style={{ paddingInlineStart: `${depth * 14}px` }}>
        <div className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-accent">
          <Tick
            state={tick}
            label={`Use everything in ${f.name}`}
            onChange={() =>
              onUnticked(
                toggle(
                  under.map((s) => s.id),
                  unticked,
                ),
              )
            }
          />
          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-1.5 text-start text-sm"
            aria-expanded={isOpen}
            onClick={() =>
              setOpen((cur) => {
                const next = new Set(cur);
                if (next.has(f.id)) next.delete(f.id);
                else next.add(f.id);
                return next;
              })
            }
          >
            {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            <FolderIcon className="size-4 text-muted-foreground" aria-hidden="true" />
            <span className="truncate">{f.name}</span>
            <span className="text-muted-foreground text-xs">{under.length}</span>
          </button>
          <span className="hidden items-center group-focus-within:flex group-hover:flex">
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={`Rename ${f.name}`}
              onClick={() => {
                const next = window.prompt("Name this folder", f.name)?.trim();
                if (next && next !== f.name) props.onRenameFolder(f, next);
              }}
            >
              <Pencil />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={`Remove folder ${f.name}`}
              onClick={() => {
                const n = under.length;
                const what = n ? ` and the ${n} source${n === 1 ? "" : "s"} in it` : "";
                if (window.confirm(`Remove the folder “${f.name}”${what}?`))
                  props.onRemoveFolder(f);
              }}
            >
              <Trash2 />
            </Button>
          </span>
        </div>
        {isOpen ? (
          <ul className="grid gap-0.5">
            {kids.map((k) => folder(k, depth + 1))}
            {own.map((s) => row(s, depth + 1))}
          </ul>
        ) : null}
      </li>
    );
  }

  const empty = sources.length === 0;
  return (
    <section aria-label="Sources" className="flex h-full min-h-0 flex-col">
      <header className="grid gap-3 border-b px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-medium text-sm">
            Sources <span className="text-muted-foreground">{sources.length}</span>
          </h2>
          <div className="flex gap-1">
            <Button type="button" size="sm" variant="outline" onClick={props.onAdd}>
              <Plus /> Add
            </Button>
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label="New folder"
              onClick={() => setNaming((v) => !v)}
            >
              <FolderPlus />
            </Button>
          </div>
        </div>
        {naming ? (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const name = folderName.trim();
              if (!name) return;
              props.onNewFolder(name);
              setFolderName("");
              setNaming(false);
            }}
          >
            <input
              aria-label="Folder name"
              value={folderName}
              maxLength={255}
              placeholder="Folder name"
              onChange={(e) => setFolderName(e.target.value)}
              className="h-8 min-w-0 flex-1 rounded-md border bg-background px-2 text-sm"
            />
            <Button type="submit" size="sm">
              Make
            </Button>
          </form>
        ) : null}
        {sources.length > 4 ? (
          <input
            type="search"
            aria-label="Find a source"
            placeholder="Find a source"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-sm"
          />
        ) : null}
      </header>
      {empty ? (
        <p className="p-6 text-center text-muted-foreground text-sm">
          Saved sources appear here. Add files, then ask questions about them.
        </p>
      ) : (
        <ul className="grid min-h-0 flex-1 content-start gap-0.5 overflow-auto p-2">
          {roots.map((f) => folder(f, 0))}
          {top.map((s) => row(s, 0))}
        </ul>
      )}
    </section>
  );
}
