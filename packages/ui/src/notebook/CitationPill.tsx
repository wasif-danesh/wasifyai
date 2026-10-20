"use client";

import type { NotebookCitation } from "@wasifyai/client";

/** A `[n]` label as a button that opens the passage it points at. */
export function CitationPill({
  n,
  citation,
  onOpen,
}: {
  n: number;
  citation: NotebookCitation | undefined;
  onOpen: (c: NotebookCitation) => void;
}) {
  if (!citation) return <span className="text-muted-foreground">[{n}]</span>;
  const where =
    citation.start_line && citation.end_line
      ? `, lines ${citation.start_line} to ${citation.end_line}`
      : "";
  return (
    <button
      type="button"
      onClick={() => onOpen(citation)}
      title={`${citation.title}${where}`}
      aria-label={`Source ${n}: ${citation.title}`}
      className="mx-0.5 inline-grid h-5 min-w-5 -translate-y-px place-items-center rounded-full bg-primary/15 px-1.5 align-middle font-semibold text-2xs text-primary hover:bg-primary/25"
    >
      {n}
    </button>
  );
}
