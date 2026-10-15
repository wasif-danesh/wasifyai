import type * as React from "react";
import { cn } from "../cn";

/** A small pill button. With `aria-pressed` it is a toggle (selected = filled); without, a plain suggestion. */
export function Chip({ className, ...props }: React.ComponentProps<"button">) {
  return (
    <button
      type="button"
      className={cn(
        "rounded-md border bg-transparent px-[0.85rem] py-[0.35rem] text-[0.92rem] transition-[background-color,border-color,color,translate] duration-200 hover:-translate-y-px hover:border-primary/50 disabled:cursor-not-allowed disabled:opacity-50 aria-pressed:border-transparent aria-pressed:bg-primary aria-pressed:text-primary-foreground",
        className,
      )}
      {...props}
    />
  );
}
