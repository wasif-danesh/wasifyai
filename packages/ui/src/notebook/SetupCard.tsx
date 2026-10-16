"use client";

import { useState } from "react";
import { Button } from "../components/button";
import { Bar } from "../components/progress-bar";
import { formatBytes } from "./format";

export type SetupItem = {
  id: "search" | "reader";
  title: string;
  /** what it is for, in one sentence */
  why: string;
  bytes: number;
  state: "missing" | "working" | "ready" | "failed" | "unavailable";
  /** 0 to 1 while it works */
  fraction?: number;
  /** a step while it works, or why it failed or is not available */
  message?: string;
  /** without it nothing can be asked; the reader alone only limits which files can be read */
  required: boolean;
};

/**
 * The pieces a notebook needs that are not on this computer yet. Nothing is fetched by itself: each
 * asks, with its size, and goes ahead only on a click.
 */
export function SetupCard({
  items,
  onStart,
}: {
  items: SetupItem[];
  onStart: (id: SetupItem["id"]) => void;
}) {
  const [asking, setAsking] = useState<SetupItem["id"] | null>(null);
  const pending = items.filter((i) => i.state !== "ready");
  if (pending.length === 0) return null;
  return (
    <section
      aria-label="Set up notebooks"
      className="mx-auto grid w-full min-w-0 max-w-3xl gap-4 rounded-2xl border bg-card p-5"
    >
      <header>
        <h2 className="font-medium text-lg">Set up reading documents</h2>
        <p className="mt-1 text-muted-foreground text-sm">
          These are downloaded once and stay on this computer. Your documents are never sent
          anywhere.
        </p>
      </header>
      <ul className="grid gap-4">
        {pending.map((i) => (
          <li key={i.id} className="grid gap-2">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium">
                  {i.title}{" "}
                  <span className="font-normal text-muted-foreground text-sm">
                    {formatBytes(i.bytes)}
                    {i.required ? "" : ", optional"}
                  </span>
                </p>
                <p className="text-muted-foreground text-sm">{i.why}</p>
              </div>
              {i.state === "missing" || i.state === "failed" ? (
                asking === i.id ? (
                  <span className="flex items-center gap-2">
                    <span className="text-sm">Download {formatBytes(i.bytes)} now?</span>
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => {
                        setAsking(null);
                        onStart(i.id);
                      }}
                    >
                      Set up
                    </Button>
                    <Button type="button" size="sm" variant="ghost" onClick={() => setAsking(null)}>
                      Cancel
                    </Button>
                  </span>
                ) : (
                  <Button type="button" size="sm" onClick={() => setAsking(i.id)}>
                    {i.state === "failed" ? "Try again" : "Set up"}
                  </Button>
                )
              ) : null}
            </div>
            {i.state === "working" ? (
              <div className="grid gap-1">
                <Bar value={i.fraction} />
                <p className="text-muted-foreground text-xs" aria-live="polite">
                  {i.message || "Working…"}
                </p>
              </div>
            ) : null}
            {i.state === "failed" && i.message ? (
              <p role="alert" className="text-destructive text-sm">
                {i.message}
              </p>
            ) : null}
            {i.state === "unavailable" && i.message ? (
              <p className="text-muted-foreground text-sm">{i.message}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
