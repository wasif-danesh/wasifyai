"use client";

import { RadioGroup as RadioGroupPrimitive } from "radix-ui";
import { useId } from "react";
import { cn } from "../cn";

export type RadioOption = { value: string; label: string; hint?: string; disabled?: boolean };

/** Pick one of a few, each with its words and an optional second line (`design/DESIGN.md`: "of a few, `RadioGroup`"). */
export function RadioGroup({
  value,
  onValueChange,
  options,
  label,
  disabled,
  className,
}: {
  value: string | undefined;
  onValueChange: (value: string) => void;
  options: RadioOption[];
  /** the question the choices answer, read by assistive tech */
  label: string;
  disabled?: boolean;
  className?: string;
}) {
  const base = useId();
  return (
    <RadioGroupPrimitive.Root
      value={value}
      onValueChange={onValueChange}
      disabled={disabled}
      aria-label={label}
      className={cn("grid gap-2.5", className)}
    >
      {options.map((o) => {
        const id = `${base}-${o.value}`;
        return (
          <div key={o.value} className="flex items-start gap-2.5">
            <RadioGroupPrimitive.Item
              id={id}
              value={o.value}
              disabled={o.disabled}
              aria-describedby={o.hint ? `${id}-hint` : undefined}
              className={cn(
                "peer mt-0.5 grid aspect-square size-5 shrink-0 place-items-center rounded-full border border-input bg-transparent outline-none transition-[color,box-shadow,border-color]",
                "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
                "disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-primary",
              )}
            >
              <RadioGroupPrimitive.Indicator className="size-2.5 rounded-full bg-primary" />
            </RadioGroupPrimitive.Item>
            <div className="grid gap-0.5 text-sm">
              <label htmlFor={id} className="select-none leading-5 peer-disabled:opacity-50">
                {o.label}
              </label>
              {o.hint ? (
                <span id={`${id}-hint`} className="text-muted-foreground text-xs">
                  {o.hint}
                </span>
              ) : null}
            </div>
          </div>
        );
      })}
    </RadioGroupPrimitive.Root>
  );
}
