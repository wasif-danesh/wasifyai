"use client";

import type { ReactNode } from "react";
import { cn } from "../cn";

/** A box that fills the window under its top bar, for a screen that is only the frame (the voice tools, 3D, Motion graphics). */
export const FRAME = "flex h-[calc(100dvh-3rem)] min-h-[32rem] flex-col";

/**
 * The one make screen (ADR-0093 decision 2): **ask** on the left (the prompt and the few controls that matter,
 * with the main button always in view at the bottom), **stage** on the right (where the result appears, in
 * every state) and **recent** under it (the last things this tool made). On a narrow screen the three stack
 * and the button stays fixed at the bottom. Every tool that makes something is built on this frame.
 */
export function MakeScreen({
  title,
  lead,
  ask,
  action,
  stage,
  recent,
  className,
}: {
  /** the tool's own heading inside the ask column (the bar carries the product's name) */
  title?: string;
  /** one line under the heading */
  lead?: ReactNode;
  ask: ReactNode;
  /** the main button and what goes with it (a reason it is off, a problem) */
  action: ReactNode;
  stage: ReactNode;
  recent?: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="make-screen"
      className={cn(
        "grid min-h-0 flex-1 grid-cols-1 overflow-auto md:grid-cols-[minmax(19rem,26rem)_minmax(0,1fr)] md:overflow-visible",
        className,
      )}
    >
      <section
        aria-label="Ask"
        className="flex flex-col border-b md:min-h-0 md:border-e md:border-b-0"
      >
        <div className="flex-1 px-6 py-5 md:min-h-0 md:overflow-auto">
          {title ? (
            <header className="mb-5 grid gap-1">
              <h1 className="m-0 font-semibold text-lg tracking-tight">{title}</h1>
              {lead ? <p className="m-0 text-muted-foreground text-sm">{lead}</p> : null}
            </header>
          ) : null}
          <div className="grid gap-5">{ask}</div>
        </div>
        <div className="sticky bottom-0 z-10 shrink-0 border-t bg-background/95 px-6 py-3 backdrop-blur md:static">
          {action}
        </div>
      </section>

      <section aria-label="Stage" className="flex min-h-[22rem] min-w-0 flex-col md:min-h-0">
        <div className="grid flex-1 place-items-center p-4 md:min-h-0 md:overflow-auto md:p-6">
          {stage}
        </div>
        {recent ? <div className="shrink-0 border-t px-6 py-3">{recent}</div> : null}
      </section>
    </div>
  );
}
