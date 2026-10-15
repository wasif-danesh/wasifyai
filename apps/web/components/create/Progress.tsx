import { Spinner } from "@/components/ui/spinner";
import { type FlowState, type Job, stepViews } from "@/lib/song-flow";
import { panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import { Bar } from "@wasifyai/ui";

function jobLine(job: Job): { text: string; value?: number } {
  switch (job.status) {
    case "queued":
      return {
        text: job.position && job.position > 1 ? `In line, place ${job.position}` : "You're next",
      };
    case "running": {
      const p = Math.round((job.progress ?? 0) * 100);
      return { text: p > 0 ? `${p}%` : "Starting", value: job.progress ?? 0 };
    }
    case "completed":
      return { text: "Done", value: 1 };
    case "failed":
      return { text: "Failed", value: job.progress };
    default:
      return { text: "Getting ready" };
  }
}

// The numbered steps: a ring with a counter, a line to the next one; one column when the box is narrow.
const STEP =
  "relative grid [counter-increment:step] justify-items-center gap-[0.45rem] text-center text-[0.85rem] text-muted-foreground " +
  "before:relative before:z-1 before:grid before:size-8 before:place-items-center before:rounded-full before:border-2 before:border-border before:bg-surface before:text-[0.85rem] before:font-bold before:transition-all before:duration-[400ms] before:content-[counter(step)] " +
  "after:absolute after:top-4 after:h-0.5 after:bg-border after:transition-colors after:duration-[400ms] after:content-[''] after:[inset-inline:calc(50%+1.25rem)_calc(-50%+1.25rem)] last:after:hidden " +
  "data-[status=done]:text-foreground data-[status=done]:before:border-ok data-[status=done]:before:bg-ok data-[status=done]:before:text-primary-foreground data-[status=done]:before:content-['✓'] data-[status=done]:after:bg-ok " +
  "data-[status=active]:font-semibold data-[status=active]:text-foreground data-[status=active]:before:animate-step-pulse data-[status=active]:before:border-primary data-[status=active]:before:text-primary data-[status=active]:before:shadow-[0_0_0_5px_var(--accent-soft)] " +
  "data-[status=failed]:text-destructive data-[status=failed]:before:border-destructive data-[status=failed]:before:bg-destructive data-[status=failed]:before:text-primary-foreground data-[status=failed]:before:content-['!'] " +
  "@max-[34rem]:grid-cols-[auto_1fr] @max-[34rem]:items-center @max-[34rem]:justify-items-start @max-[34rem]:gap-[0.8rem] @max-[34rem]:text-start " +
  "@max-[34rem]:after:inset-[2rem_auto_-0.7rem_1rem] @max-[34rem]:after:h-auto @max-[34rem]:after:w-0.5";

/** The stepper, plus a live bar while a music or cover job is queued or running. */
export function Progress({ state }: { state: FlowState }) {
  const steps = stepViews(state);
  const working = state.phase === "generating" || state.phase === "answering";
  const job = state.step === "cover" ? state.cover : state.music;
  const line = jobLine(job);
  const showBar =
    state.phase === "generating" && (state.step === "music" || state.step === "cover");
  const busy = !["approving", "done", "refused", "error", "idle"].includes(state.phase);

  return (
    <section className={cn(panel, "@container")} aria-label="Progress">
      <div className="flex items-center gap-[0.8rem] font-semibold">
        {busy ? <Spinner /> : null}
        <span>{state.label || "Working"}</span>
      </div>

      <ol className="grid list-none grid-cols-5 gap-1 p-0 [counter-reset:step] @max-[34rem]:grid-cols-1 @max-[34rem]:gap-[0.6rem]">
        {steps.map((s) => (
          <li
            key={s.id}
            data-status={s.status}
            aria-current={s.status === "active" ? "step" : undefined}
            className={STEP}
          >
            <span>{s.label}</span>
            <span className="sr-only">
              {s.status === "done"
                ? "(done)"
                : s.status === "active"
                  ? "(in progress)"
                  : s.status === "failed"
                    ? "(failed)"
                    : ""}
            </span>
          </li>
        ))}
      </ol>

      {showBar ? (
        <div className="grid gap-[0.6rem]">
          <div className="flex justify-between gap-4 text-[0.95rem] text-muted-foreground tabular-nums">
            <span>{state.step === "music" ? "Composing the track" : "Painting the cover"}</span>
            <span>{line.text}</span>
          </div>
          {/* The visible bar is decorative; a native <progress> carries the value for assistive tech. */}
          <progress
            className="sr-only"
            aria-label={state.step === "music" ? "Music progress" : "Cover progress"}
            max={100}
            value={line.value === undefined ? undefined : Math.round(line.value * 100)}
          />
          <Bar value={line.value} />
        </div>
      ) : null}
      {working && !showBar ? <p className="text-muted-foreground">One moment…</p> : null}
    </section>
  );
}

export { Bar };
