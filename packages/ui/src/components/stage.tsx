"use client";

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../cn";
import { type Action, ActionsRow } from "./actions-row";
import { Button } from "./button";
import { EmptyState } from "./empty-state";
import { ErrorNotice } from "./error-notice";
import { Bar } from "./progress-bar";
import { Spinner } from "./spinner";

export type StageState =
  | { kind: "empty"; icon?: LucideIcon; title: string; text?: ReactNode; action?: ReactNode }
  | {
      kind: "working";
      /** what is being made ("Making your picture") */
      label: string;
      /** how far, in words ("about 40 seconds left", "step 2 of 4") */
      text?: string;
      /** 0 to 1 when known */
      value?: number;
      onStop?: () => void;
    }
  | {
      kind: "error";
      /** "That did not work" unless the error is of another kind ("We can't make that one") */
      title?: string;
      message: string;
      details?: string;
      onRetry?: () => void;
      onReset?: () => void;
    }
  | { kind: "result"; children: ReactNode; actions?: Action[]; caption?: ReactNode };

/**
 * Where the result of a make screen appears (ADR-0093): one area with its four states, so a person always knows
 * where to look. Empty says what goes here; working shows what, how far and Stop; error says what happened in
 * plain words; result shows the thing with its three actions and a menu.
 */
export function Stage({
  state,
  minHeight = "min-h-[20rem]",
  className,
}: {
  state: StageState;
  /** a Tailwind class for the area's height when empty or working */
  minHeight?: string;
  className?: string;
}) {
  return (
    <section
      aria-label="Result"
      aria-live={state.kind === "working" || state.kind === "error" ? "polite" : undefined}
      data-slot="stage"
      data-state={state.kind}
      className={cn(
        "relative grid rounded-lg border bg-surface",
        state.kind === "result" ? "gap-3 p-3" : cn("place-items-center p-6", minHeight),
        className,
      )}
    >
      {state.kind === "empty" ? (
        <EmptyState icon={state.icon} title={state.title} text={state.text} action={state.action} />
      ) : null}
      {state.kind === "working" ? (
        <div className="grid w-full max-w-md justify-items-center gap-3 text-center">
          <Spinner className="size-6" />
          <div className="font-semibold">{state.label}</div>
          {state.text ? <div className="text-muted-foreground text-sm">{state.text}</div> : null}
          <Bar value={state.value} className="w-full" />
          <progress
            className="sr-only"
            aria-label={state.label}
            max={100}
            value={state.value === undefined ? undefined : Math.round(state.value * 100)}
          />
          {state.onStop ? (
            <Button type="button" variant="outline" size="sm" onClick={state.onStop}>
              Stop
            </Button>
          ) : null}
        </div>
      ) : null}
      {state.kind === "error" ? (
        <div className="w-full max-w-xl">
          <ErrorNotice
            title={state.title}
            message={state.message}
            details={state.details}
            onRetry={state.onRetry}
            onReset={state.onReset}
          />
        </div>
      ) : null}
      {state.kind === "result" ? (
        <>
          <div className="grid max-w-full place-items-center overflow-hidden rounded-md [&>img]:max-h-[calc(100dvh-22rem)] [&>img]:max-w-full [&>video]:max-h-[calc(100dvh-22rem)]">
            {state.children}
          </div>
          {state.caption ? (
            <div className="text-muted-foreground text-sm">{state.caption}</div>
          ) : null}
          {state.actions?.length ? <ActionsRow actions={state.actions} /> : null}
        </>
      ) : null}
    </section>
  );
}
