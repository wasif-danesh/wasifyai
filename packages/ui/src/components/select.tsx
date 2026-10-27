"use client";

import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { Select as SelectPrimitive } from "radix-ui";

import { cn } from "../cn";

export type SelectOption = {
  value: string;
  label: string;
  /** a second, quieter line */
  hint?: string;
  disabled?: boolean;
};

export type SelectGroup = { label: string; options: SelectOption[] };

/**
 * Pick one of many (`design/DESIGN.md`: "of many, `Select`"). A list box in the app's own look, in both themes,
 * with the keyboard behaviour of a native select: type to jump, arrows to move, Enter to choose. Options come as
 * a flat list or as named groups.
 */
export function Select({
  id,
  value,
  onValueChange,
  options,
  placeholder = "Choose…",
  disabled,
  className,
  "aria-label": ariaLabel,
  "aria-describedby": describedBy,
  "aria-invalid": invalid,
}: {
  id?: string;
  value: string | undefined;
  onValueChange: (value: string) => void;
  options: SelectOption[] | SelectGroup[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
}) {
  const groups: SelectGroup[] = isGrouped(options) ? options : [{ label: "", options }];
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectPrimitive.Trigger
        id={id}
        data-slot="select-trigger"
        aria-label={ariaLabel}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        className={cn(
          "flex h-10 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-transparent px-3 py-2 text-start text-sm outline-none transition-[color,box-shadow]",
          "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
          "disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-muted-foreground",
          "aria-invalid:border-destructive aria-invalid:ring-destructive/20",
          "*:data-[slot=select-value]:line-clamp-1 [&_svg]:shrink-0",
          className,
        )}
      >
        <SelectPrimitive.Value data-slot="select-value" placeholder={placeholder} />
        <SelectPrimitive.Icon asChild>
          <ChevronDownIcon className="size-4 opacity-60" aria-hidden="true" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className={cn(
            "z-50 max-h-(--radix-select-content-available-height) min-w-(--radix-select-trigger-width) overflow-y-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-card",
          )}
        >
          <SelectPrimitive.Viewport>
            {groups.map((g, i) => (
              <SelectPrimitive.Group key={g.label || i}>
                {g.label ? (
                  <SelectPrimitive.Label className="px-2 py-1.5 text-muted-foreground text-xs">
                    {g.label}
                  </SelectPrimitive.Label>
                ) : null}
                {g.options.map((o) => (
                  <SelectPrimitive.Item
                    key={o.value}
                    value={o.value}
                    disabled={o.disabled}
                    className={cn(
                      "relative flex w-full cursor-default select-none items-start gap-2 rounded-sm py-1.5 ps-2 pe-8 text-sm outline-hidden",
                      "focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
                    )}
                  >
                    <span className="absolute end-2 top-2 flex size-3.5 items-center justify-center">
                      <SelectPrimitive.ItemIndicator>
                        <CheckIcon className="size-4" aria-hidden="true" />
                      </SelectPrimitive.ItemIndicator>
                    </span>
                    <span className="grid min-w-0">
                      <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                      {o.hint ? (
                        <span className="text-muted-foreground text-xs">{o.hint}</span>
                      ) : null}
                    </span>
                  </SelectPrimitive.Item>
                ))}
              </SelectPrimitive.Group>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

function isGrouped(options: SelectOption[] | SelectGroup[]): options is SelectGroup[] {
  return options.length > 0 && "options" in (options[0] as object);
}
