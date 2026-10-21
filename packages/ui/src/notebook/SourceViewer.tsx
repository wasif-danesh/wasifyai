"use client";

import type { NotebookSource, NotebooksApi } from "@wasifyai/client";
import { ArrowLeft, Download } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Markdown } from "../chat/markdown";
import { Button } from "../components/button";
import { useSaveCopy } from "../save";

export type Highlight = {
  start: number | null;
  end: number | null;
  /** the passage as it was when an answer cited it, shown if the source is gone */
  snapshot?: string;
};

/** Split Markdown at the cited lines (1-based, inclusive). */
export function splitAt(
  content: string,
  start: number | null,
  end: number | null,
): { before: string; mark: string; after: string } | null {
  if (!start || !end || end < start) return null;
  const lines = content.split("\n");
  if (start > lines.length) return null;
  return {
    before: lines.slice(0, start - 1).join("\n"),
    mark: lines.slice(start - 1, end).join("\n"),
    after: lines.slice(end).join("\n"),
  };
}

export type SourceViewerProps = {
  api: NotebooksApi;
  notebookId: string;
  sourceId: string;
  /** Opened from a citation: the passage to show. */
  highlight?: Highlight | null;
  onBack: () => void;
  /** A note was saved (the list should be read again). */
  onChanged?: () => void;
};

/**
 * One source as the notebook reads it: its text (Markdown), with the cited passage marked, and the
 * stored file to save. A source that is gone still shows the passage an answer cited.
 */
export function SourceViewer({
  api,
  notebookId,
  sourceId,
  highlight,
  onBack,
  onChanged,
}: SourceViewerProps) {
  const [source, setSource] = useState<NotebookSource | null>(null);
  const [gone, setGone] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const mark = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setSource(null);
    setGone(false);
    api
      .source(notebookId, sourceId)
      .then((s) => !cancelled && setSource(s))
      .catch((e) => {
        if (cancelled) return;
        if (e && typeof e === "object" && "status" in e && e.status === 404) setGone(true);
        else setProblem(e instanceof Error ? e.message : "The source could not be opened.");
      });
    return () => {
      cancelled = true;
    };
  }, [api, notebookId, sourceId]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll once the text is there
  useEffect(() => {
    mark.current?.scrollIntoView?.({ block: "center" });
  }, [source]);

  const saveCopy = useSaveCopy();
  async function download() {
    if (!source) return;
    try {
      await saveCopy({ name: source.title, blob: () => api.original(notebookId, source.id) });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The file could not be saved.");
    }
  }

  async function save() {
    if (!source || draft === null || !draft.trim()) return;
    try {
      const next = await api.editNote(notebookId, source.id, draft);
      setSource({ ...source, ...next, content: draft });
      setDraft(null);
      onChanged?.();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The note could not be saved.");
    }
  }

  const parts =
    source?.content && highlight ? splitAt(source.content, highlight.start, highlight.end) : null;

  return (
    <section aria-label="Source" className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-2 border-b px-3 py-2.5">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Back to sources"
          onClick={onBack}
        >
          <ArrowLeft />
        </Button>
        <h2 className="min-w-0 flex-1 truncate font-medium text-sm" title={source?.title}>
          {source?.title ?? (gone ? "Source removed" : "Opening…")}
        </h2>
        {source?.kind === "file" ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Save the original"
            onClick={() => void download()}
          >
            <Download />
          </Button>
        ) : null}
      </header>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
        {problem ? (
          <p role="alert" className="mb-3 text-destructive text-sm">
            {problem}
          </p>
        ) : null}
        {gone ? (
          <div className="grid gap-3">
            <p className="text-muted-foreground text-sm">
              This source was removed from the notebook. This is the passage the answer used.
            </p>
            {highlight?.snapshot ? (
              <blockquote className="rounded-lg border-s-4 border-primary bg-primary/5 p-3">
                <Markdown text={highlight.snapshot} />
              </blockquote>
            ) : null}
          </div>
        ) : null}
        {source && source.status !== "ready" ? (
          <p className="text-muted-foreground text-sm">
            {source.status === "failed"
              ? (source.error ?? "This source could not be read.")
              : "This source is still being read."}
          </p>
        ) : null}
        {source?.status === "ready" && draft === null ? (
          <div className="grid gap-3">
            {source.kind === "note" ? (
              <div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setDraft(source.content ?? "")}
                >
                  Edit note
                </Button>
              </div>
            ) : null}
            {parts ? (
              <>
                {parts.before.trim() ? <Markdown text={parts.before} /> : null}
                <div
                  ref={mark}
                  className="rounded-lg border-s-4 border-primary bg-primary/10 px-3 py-2"
                >
                  <Markdown text={parts.mark} />
                </div>
                {parts.after.trim() ? <Markdown text={parts.after} /> : null}
              </>
            ) : (
              <Markdown text={source.content ?? ""} />
            )}
          </div>
        ) : null}
        {draft !== null ? (
          <div className="grid gap-2">
            <textarea
              aria-label="Note text"
              value={draft}
              rows={14}
              onChange={(e) => setDraft(e.target.value)}
              className="w-full rounded-md border bg-background p-3"
            />
            <div className="flex gap-2">
              <Button type="button" onClick={() => void save()} disabled={!draft.trim()}>
                Save
              </Button>
              <Button type="button" variant="ghost" onClick={() => setDraft(null)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
