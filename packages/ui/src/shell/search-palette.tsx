"use client";

import type { CreationsApi } from "@wasifyai/client";
import { Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { cn } from "../cn";
import { Modal } from "../components/dialog";
import { type Entry, longEnough, toRow } from "../creations/model";
import { useCreationSearch } from "../creations/use-creation-search";

export type Place = { id: string; label: string; hint?: string; onSelect: () => void };

/**
 * ⌘K: a box that opens any tool by name and finds a creation by what it is about, in any language (the
 * one search of ADR-0093, on the window and on the web). Arrow keys move, Enter opens, Escape closes.
 */
export function SearchPalette({
  open,
  onClose,
  places,
  creations,
  onOpenCreation,
}: {
  open: boolean;
  onClose: () => void;
  /** every tool, with its words; filtered by what is typed */
  places: Place[];
  /** the library to search; left out, only tools are found */
  creations?: CreationsApi;
  onOpenCreation?: (entry: Entry) => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  const searching = longEnough(query);
  const search = useCreationSearch(creations ?? NONE, creations && open ? query : "", "all");
  const needle = query.trim().toLowerCase();
  const matches = useMemo(
    () =>
      places.filter(
        (p) =>
          !needle ||
          p.label.toLowerCase().includes(needle) ||
          (p.hint?.toLowerCase().includes(needle) ?? false),
      ),
    [places, needle],
  );
  const found = search.status === "done" && searching ? search.entries : [];
  const rows: { key: string; label: string; hint?: string; go: () => void }[] = [
    ...found.map((entry) => {
      const row = toRow(entry);
      return {
        key: row.key,
        label: row.title,
        hint: row.kindLabel,
        go: () => onOpenCreation?.(entry),
      };
    }),
    ...matches.map((p) => ({ key: `place:${p.id}`, label: p.label, hint: p.hint, go: p.onSelect })),
  ];
  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      requestAnimationFrame(() => input.current?.focus());
    }
  }, [open]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new list starts at the top
  useEffect(() => setActive(0), [query, found.length]);
  if (!open) return null;
  const pick = (i: number) => {
    const row = rows[i];
    if (!row) return;
    onClose();
    row.go();
  };
  return (
    <Modal label="Search" onClose={onClose}>
      <div className="flex items-center gap-2 rounded-md border px-3">
        <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <input
          ref={input}
          type="search"
          aria-controls={listId}
          aria-label="Search"
          placeholder="A tool, or something you made…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(rows.length - 1, a + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(0, a - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              pick(active);
            }
          }}
          className="h-10 w-full min-w-0 bg-transparent text-base outline-none placeholder:text-muted-foreground"
        />
        <kbd className="hidden rounded border px-1.5 text-muted-foreground text-xs sm:inline">
          esc
        </kbd>
      </div>
      <p className="sr-only" aria-live="polite">
        {rows.length === 1 ? "1 result" : `${rows.length} results`}
      </p>
      <ul
        id={listId}
        aria-label="Results"
        className="m-0 grid max-h-[50vh] list-none gap-0.5 overflow-y-auto p-0"
      >
        {searching && search.status === "searching" ? (
          <p className="m-0 px-3 py-2 text-muted-foreground text-sm">Searching…</p>
        ) : null}
        {searching && search.status === "error" ? (
          <p className="m-0 px-3 py-2 text-destructive text-sm">{search.message}</p>
        ) : null}
        {found.length > 0 ? <Heading>Your creations</Heading> : null}
        {rows.map((row, i) => (
          <li key={row.key}>
            {i === found.length && matches.length > 0 ? (
              <Heading>{needle ? "Tools" : "Go to"}</Heading>
            ) : null}
            <button
              id={`${listId}-${i}`}
              type="button"
              aria-current={i === active ? "true" : undefined}
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(i)}
              className={cn(
                "flex w-full items-center gap-3 rounded-md px-3 py-2 text-start text-sm outline-none",
                i === active && "bg-accent",
              )}
            >
              <span className="min-w-0 flex-1 truncate">{row.label}</span>
              {row.hint ? (
                <span className="shrink-0 text-muted-foreground text-xs">{row.hint}</span>
              ) : null}
            </button>
          </li>
        ))}
        {rows.length === 0 ? (
          <p className="m-0 px-3 py-2 text-muted-foreground text-sm">
            {searching && search.status === "done"
              ? `Nothing matched “${query}”.`
              : "Nothing here."}
          </p>
        ) : null}
      </ul>
    </Modal>
  );
}

function Heading({ children }: { children: string }) {
  return (
    <div className="px-3 pt-2 pb-1 font-medium text-muted-foreground text-xs uppercase tracking-wider">
      {children}
    </div>
  );
}

const NONE: CreationsApi = {
  search: async () => ({ results: [], degraded: false, words: [] }),
  cards: async () => ({ speeches: [], transcripts: [], songs: [], lipsyncs: [] }),
} as unknown as CreationsApi;
