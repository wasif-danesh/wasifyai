"use client";

import { ToggleGroup as ToggleGroupPrimitive } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "../cn";

export type SegmentedOption = { value: string; label: ReactNode; disabled?: boolean };

/** One of a few, side by side, always with one chosen: the tabs of a screen's modes, a shape, a length. */
export function Segmented({
  value,
  onValueChange,
  options,
  label,
  size = "default",
  className,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: SegmentedOption[];
  /** what is being chosen, read by assistive tech */
  label: string;
  size?: "sm" | "default";
  className?: string;
}) {
  return (
    <ToggleGroupPrimitive.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onValueChange(v)}
      aria-label={label}
      className={cn(
        "inline-flex w-fit max-w-full items-center gap-1 rounded-md border bg-muted/60 p-1",
        className,
      )}
    >
      {options.map((o) => (
        <ToggleGroupPrimitive.Item
          key={o.value}
          value={o.value}
          disabled={o.disabled}
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-[0.3rem] px-3 font-medium text-muted-foreground text-sm outline-none transition-[background-color,color,box-shadow]",
            size === "sm" ? "h-7 px-2.5 text-xs" : "h-8",
            "hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50",
            "data-[state=on]:bg-surface data-[state=on]:text-foreground data-[state=on]:shadow-xs",
          )}
        >
          {o.label}
        </ToggleGroupPrimitive.Item>
      ))}
    </ToggleGroupPrimitive.Root>
  );
}
