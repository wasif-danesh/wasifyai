// SPDX-License-Identifier: AGPL-3.0-only
import { cn } from "@wasifyai/ui";
import { humanBytes } from "./engine";
import type { Fit } from "./models";

const WORDS = { fits: "Fits", tight: "Tight", too_big: "Too big" } as const;
const TONE = {
  fits: "border-ok/40 text-ok",
  tight: "border-warn/50 text-warn",
  too_big: "border-destructive/50 text-destructive",
} as const;

/** "Fits · needs about 12 GB": the verdict and the number it rests on. */
export function FitBadge({ fit, className }: { fit: Fit; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-xs", className)}>
      <span className={cn("rounded-full border px-2 py-0.5", TONE[fit.verdict])}>
        {WORDS[fit.verdict]}
      </span>
      <span className="text-muted-foreground">
        needs {fit.estimate ? "about " : ""}
        {humanBytes(fit.needed_bytes)}
      </span>
    </span>
  );
}
