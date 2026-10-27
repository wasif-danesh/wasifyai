"use client";

import { Slider as SliderPrimitive } from "radix-ui";
import { cn } from "../cn";

/**
 * A number on a range, with its value said in words beside it ("0:30", "1.5×"). The track and thumb are the
 * app's own, so the control looks the same in both themes and on every platform.
 */
export function Slider({
  id,
  value,
  onValueChange,
  min = 0,
  max = 100,
  step = 1,
  label,
  format = (v) => String(v),
  disabled,
  className,
}: {
  id?: string;
  value: number;
  onValueChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  /** what the number is, read by assistive tech */
  label: string;
  /** the value in words, shown at the end and read out */
  format?: (value: number) => string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <SliderPrimitive.Root
        id={id}
        value={[value]}
        onValueChange={([v]) => v !== undefined && onValueChange(v)}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        className="relative flex h-5 w-full touch-none select-none items-center data-[disabled]:opacity-50"
      >
        <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-muted">
          <SliderPrimitive.Range className="absolute h-full bg-primary" />
        </SliderPrimitive.Track>
        <SliderPrimitive.Thumb
          aria-label={label}
          aria-valuetext={format(value)}
          className={cn(
            "block size-5 rounded-full border-2 border-primary bg-background shadow-xs outline-none transition-[box-shadow]",
            "hover:ring-4 hover:ring-ring/30 focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none",
          )}
        />
      </SliderPrimitive.Root>
      <output className="min-w-[3.5rem] text-end text-muted-foreground text-sm tabular-nums">
        {format(value)}
      </output>
    </div>
  );
}
