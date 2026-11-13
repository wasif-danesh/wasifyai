import { CheckIcon } from "lucide-react";
import { cn } from "../cn";

/**
 * Where a person is in a flow of a few steps ("1 Add pictures · 2 Check · 3 Teach"). Done steps show a tick, the
 * current one is strong, the rest are quiet; a done step can be clicked to go back when `onStep` is given.
 */
export function Stepper({
  steps,
  current,
  onStep,
  className,
}: {
  steps: string[];
  /** 0-based */
  current: number;
  onStep?: (index: number) => void;
  className?: string;
}) {
  return (
    <ol className={cn("flex flex-wrap items-center gap-2", className)} aria-label="Steps">
      {steps.map((step, i) => {
        const state = i < current ? "done" : i === current ? "current" : "upcoming";
        const body = (
          <>
            <span
              aria-hidden="true"
              className={cn(
                "grid size-5 shrink-0 place-items-center rounded-full font-semibold text-xs",
                state === "done" && "bg-primary text-primary-foreground",
                state === "current" && "bg-primary text-primary-foreground",
                state === "upcoming" && "border text-muted-foreground",
              )}
            >
              {state === "done" ? <CheckIcon className="size-3" strokeWidth={3} /> : i + 1}
            </span>
            <span>{step}</span>
          </>
        );
        const look = cn(
          "inline-flex items-center gap-2 rounded-full py-1 ps-1 pe-3 text-sm",
          state === "current" && "bg-accent font-semibold text-foreground",
          state !== "current" && "text-muted-foreground",
        );
        return (
          <li
            key={step}
            aria-current={state === "current" ? "step" : undefined}
            data-state={state}
            className="flex items-center gap-2"
          >
            {state === "done" && onStep ? (
              <button
                type="button"
                className={cn(look, "hover:bg-accent")}
                onClick={() => onStep(i)}
              >
                {body}
              </button>
            ) : (
              <span className={look}>{body}</span>
            )}
            {i < steps.length - 1 ? (
              <span aria-hidden="true" className="h-px w-4 bg-border" />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
