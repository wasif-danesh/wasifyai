"use client";

import type { GuideState } from "@wasifyai/client";
import { Loader2, RotateCw } from "lucide-react";
import { Button } from "../components/button";

export type SourceGuideProps = {
  state: GuideState | null;
  making: boolean;
  problem: string | null;
  /** Make the guide again (it is stale, or it failed). */
  onMake: () => void;
  /** Put a question in the box. */
  onAsk: (question: string) => void;
};

/** What the sources are about, and three questions to start with. Shown above an empty thread. */
export function SourceGuide({ state, making, problem, onMake, onAsk }: SourceGuideProps) {
  const guide = state?.guide ?? null;
  if (!guide && !making && !problem) return null;
  return (
    <section
      aria-label="Source guide"
      className="mx-auto grid w-full max-w-3xl gap-3 rounded-2xl border bg-card p-5"
    >
      <header className="flex items-center justify-between gap-2">
        <h2 className="font-medium text-sm">Source guide</h2>
        {guide && state?.stale && !making ? (
          <Button type="button" variant="ghost" size="xs" onClick={onMake}>
            <RotateCw /> Sources changed, update
          </Button>
        ) : null}
      </header>
      {making && !guide ? (
        <p className="flex items-center gap-2 text-muted-foreground text-sm" aria-live="polite">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Reading your sources to
          write a summary…
        </p>
      ) : null}
      {guide ? (
        <>
          <p className="text-sm leading-relaxed">{guide.summary}</p>
          {guide.topics.length ? (
            <ul className="flex flex-wrap gap-1.5" aria-label="Topics">
              {guide.topics.map((t) => (
                <li
                  key={t}
                  className="rounded-full border px-2.5 py-0.5 text-muted-foreground text-xs"
                >
                  {t}
                </li>
              ))}
            </ul>
          ) : null}
          <ul className="grid gap-1.5" aria-label="Questions to start with">
            {guide.questions.map((q) => (
              <li key={q}>
                <button
                  type="button"
                  onClick={() => onAsk(q)}
                  className="w-full rounded-xl border px-3 py-2 text-start text-sm hover:bg-accent"
                >
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {problem && !making ? (
        <div className="grid gap-2">
          <p role="alert" className="text-destructive text-sm">
            {problem}
          </p>
          <div>
            <Button type="button" size="sm" variant="outline" onClick={onMake}>
              Try again
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
