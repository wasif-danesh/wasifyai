import { ChevronRightIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../cn";

/**
 * The collapsed section a screen keeps its technical settings in (ADR-0073, `design/DESIGN.md`): closed by default,
 * one line to open it. Seeds, tempos, keys, speeds and the like live here, never on the first screen.
 */
export function Experts({
  title = "For experts",
  summary,
  open,
  children,
  className,
}: {
  title?: string;
  /** a few words after the title that say what is inside ("seed, tempo, key") */
  summary?: string;
  /** open from the start (a test, or a person who opened it last time) */
  open?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <details className={cn("group rounded-md border", className)} open={open} data-slot="experts">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm marker:hidden [&::-webkit-details-marker]:hidden">
        <ChevronRightIcon
          aria-hidden="true"
          className="size-4 text-muted-foreground transition-transform group-open:rotate-90"
        />
        <span className="font-medium">{title}</span>
        {summary ? <span className="text-muted-foreground">{summary}</span> : null}
      </summary>
      <div className="grid gap-4 border-t px-3 py-3">{children}</div>
    </details>
  );
}
