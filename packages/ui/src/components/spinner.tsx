import { cn } from "../cn";

/** A small spinning ring in the current text colour; decorative (the text next to it says what is happening). */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block size-[1.1rem] shrink-0 animate-spin rounded-full border-2 border-current/25 border-t-current",
        className,
      )}
    />
  );
}
