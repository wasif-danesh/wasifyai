"use client";

import { DropdownMenu as MenuPrimitive } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "../cn";

export type MenuItem = {
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  destructive?: boolean;
  disabled?: boolean;
};

/** A small menu under a button: the quieter actions of a thing. Arrow keys move, Enter chooses, Escape closes. */
export function Menu({
  trigger,
  items,
  align = "end",
}: {
  /** the button that opens it (it gets the menu's state) */
  trigger: ReactNode;
  items: MenuItem[];
  align?: "start" | "end";
}) {
  return (
    <MenuPrimitive.Root modal={false}>
      <MenuPrimitive.Trigger asChild>{trigger}</MenuPrimitive.Trigger>
      <MenuPrimitive.Portal>
        <MenuPrimitive.Content
          align={align}
          sideOffset={4}
          className="z-50 min-w-[10rem] rounded-md border bg-popover p-1 text-popover-foreground shadow-card"
        >
          {items.map((item) => (
            <MenuPrimitive.Item
              key={item.label}
              disabled={item.disabled}
              onSelect={item.onSelect}
              className={cn(
                "flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden",
                "focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
                item.destructive &&
                  "text-destructive focus:bg-destructive/10 focus:text-destructive",
                "[&_svg]:size-4 [&_svg]:shrink-0",
              )}
            >
              {item.icon}
              {item.label}
            </MenuPrimitive.Item>
          ))}
        </MenuPrimitive.Content>
      </MenuPrimitive.Portal>
    </MenuPrimitive.Root>
  );
}
