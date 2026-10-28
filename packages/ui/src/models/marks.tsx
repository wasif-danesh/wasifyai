"use client";

import { cn } from "../cn";
import { COMMERCIAL } from "./ModelSelect";
import type { ModelChoice } from "./types";

export type Readiness = "ready" | "getting" | "needs" | "cannot" | "none";

const DOT: Record<Readiness, { className: string; label: string }> = {
  ready: { className: "bg-ok", label: "Ready" },
  getting: { className: "animate-pulse bg-warn", label: "Downloading" },
  needs: { className: "border border-muted-foreground bg-transparent", label: "Needs a download" },
  cannot: { className: "bg-warn", label: "Cannot run here" },
  none: { className: "bg-muted-foreground/50", label: "No model chosen" },
};

/** A model's readiness in one look (ADR-0093 U11): the same dot on the bar's model button, the picker and Models. */
export function ReadyDot({ state, className }: { state: Readiness; className?: string }) {
  const d = DOT[state];
  return (
    <span
      data-slot="ready-dot"
      data-state={state}
      role="img"
      aria-label={d.label}
      title={d.label}
      className={cn("inline-block size-2 shrink-0 rounded-full", d.className, className)}
    />
  );
}

export function readinessOf(c: Pick<ModelChoice, "state">): Readiness {
  return c.state === "ready" ? "ready" : c.state === "needs_download" ? "needs" : "cannot";
}

/** The licence on one line: its name, marked when it is not for commercial use or was not reviewed. */
export function LicenceChip({ choice }: { choice: Pick<ModelChoice, "licence" | "commercial"> }) {
  const unknown = !choice.licence || choice.licence.toLowerCase() === "unknown";
  const caution = choice.commercial !== "yes";
  return (
    <span
      title={COMMERCIAL[choice.commercial]}
      className={cn(
        "inline-flex max-w-full items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs",
        caution ? "bg-warn/10" : "bg-muted",
      )}
    >
      <span className="truncate">{unknown ? "Licence unknown" : choice.licence}</span>
      {caution && !unknown ? (
        <span className="text-muted-foreground">
          ·{" "}
          {choice.commercial === "no"
            ? "not commercial"
            : choice.commercial === "conditional"
              ? "conditions"
              : "not reviewed"}
        </span>
      ) : null}
      <span className="sr-only">{COMMERCIAL[choice.commercial]}</span>
    </span>
  );
}
