import { cn } from "../cn";

/** A progress bar: filled to a value, or sliding while the job is only waiting its turn. */
export function Bar({ value, className }: { value?: number; className?: string }) {
  return (
    <div
      aria-hidden="true"
      data-slot="bar"
      className={cn("h-[0.6rem] overflow-hidden rounded-full bg-muted", className)}
      data-indeterminate={value === undefined || undefined}
    >
      <i
        className={cn(
          "block h-full rounded-[inherit] bg-primary transition-[width] duration-500 ease-out-soft",
          value === undefined && "w-2/5 animate-slide",
        )}
        style={
          value === undefined ? undefined : { width: `${Math.min(1, Math.max(0, value)) * 100}%` }
        }
      />
    </div>
  );
}
