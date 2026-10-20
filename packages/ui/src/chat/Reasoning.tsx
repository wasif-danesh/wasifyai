"use client";

import { Spinner } from "../components/spinner";

/**
 * A model's thinking (ADR-0083), under the answer it led to: closed by default, a plain `<details>` so it opens by keyboard and is read
 * by a screen reader as it is. The text is the model's own and is shown as plain text, never as markup. While it is still thinking the
 * summary says so.
 */
export function Reasoning({ text, running }: { text: string; running?: boolean }) {
  return (
    <details className="group rounded-lg border bg-card text-sm" data-reasoning="">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground marker:hidden [&::-webkit-details-marker]:hidden">
        {running ? <Spinner /> : null}
        <span>{running ? "Thinking…" : "Thinking"}</span>
        <span aria-hidden="true" className="ms-auto text-xs group-open:hidden">
          Show
        </span>
        <span aria-hidden="true" className="ms-auto hidden text-xs group-open:inline">
          Hide
        </span>
      </summary>
      <p
        dir="auto"
        className="max-h-80 overflow-auto whitespace-pre-wrap break-words border-t px-3 py-2 text-muted-foreground"
      >
        {text}
      </p>
    </details>
  );
}
