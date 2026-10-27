"use client";

import { MoreHorizontalIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../cn";
import { Button } from "./button";
import { Menu, type MenuItem } from "./menu";

export type Action = {
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  destructive?: boolean;
  disabled?: boolean;
};

/**
 * What can be done with a thing: at most three buttons, the first one strong, and everything else behind a
 * "More" menu (ADR-0093: "three actions and a menu", never a row of eleven verbs).
 */
export function ActionsRow({
  actions,
  shown = 3,
  size = "sm",
  className,
}: {
  actions: Action[];
  /** how many stay as buttons; the rest go in the menu */
  shown?: number;
  size?: "sm" | "default";
  className?: string;
}) {
  const buttons = actions.slice(0, shown);
  const more: MenuItem[] = actions.slice(shown);
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)} data-slot="actions-row">
      {buttons.map((a, i) => (
        <Button
          key={a.label}
          type="button"
          size={size}
          variant={i === 0 ? "default" : a.destructive ? "ghost" : "outline"}
          disabled={a.disabled}
          onClick={a.onSelect}
          className={cn(a.destructive && i > 0 && "text-destructive")}
        >
          {a.icon}
          {a.label}
        </Button>
      ))}
      {more.length > 0 ? (
        <Menu
          items={more}
          trigger={
            <Button type="button" size={size} variant="outline" aria-label="More">
              <MoreHorizontalIcon aria-hidden="true" />
              More
            </Button>
          }
        />
      ) : null}
    </div>
  );
}
