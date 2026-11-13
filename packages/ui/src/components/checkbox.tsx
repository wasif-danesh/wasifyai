"use client";

import { CheckIcon } from "lucide-react";
import { Checkbox as CheckboxPrimitive } from "radix-ui";
import { useId } from "react";
import { cn } from "../cn";

/** A yes-or-no choice with its words beside it; the box is drawn by the app, so it matches both themes. */
export function Checkbox({
  id,
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
  className,
}: {
  id?: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
  className?: string;
}) {
  const own = useId();
  const boxId = id ?? own;
  const hintId = `${boxId}-hint`;
  return (
    <div className={cn("flex items-start gap-2.5", className)}>
      <CheckboxPrimitive.Root
        id={boxId}
        checked={checked}
        onCheckedChange={(v) => onCheckedChange(v === true)}
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        className={cn(
          "peer mt-0.5 grid size-5 shrink-0 place-items-center rounded-sm border border-input bg-transparent outline-none transition-[color,box-shadow,background-color]",
          "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground",
        )}
      >
        <CheckboxPrimitive.Indicator>
          <CheckIcon className="size-3.5" aria-hidden="true" strokeWidth={3} />
        </CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      <div className="grid gap-0.5 text-sm">
        <label htmlFor={boxId} className="select-none leading-5 peer-disabled:opacity-50">
          {label}
        </label>
        {hint ? (
          <span id={hintId} className="text-muted-foreground text-xs">
            {hint}
          </span>
        ) : null}
      </div>
    </div>
  );
}
