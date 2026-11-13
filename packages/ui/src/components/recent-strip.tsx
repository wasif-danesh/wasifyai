"use client";

import type { ReactNode } from "react";
import { cn } from "../cn";
import { Button } from "./button";
import { Skeleton } from "./skeleton";

export type RecentItem = {
  id: string;
  /** the thumbnail: an image, a cover tile, an icon */
  cover: ReactNode;
  /** what it is, read by assistive tech and shown as a tooltip */
  label: string;
  onOpen: () => void;
  current?: boolean;
};

/**
 * The last things a tool made, in a row under its stage, each opening in place, with "See all" to the Library.
 * This is the shell; a later stage feeds it from the one library (ADR-0093 decision 5).
 */
export function RecentStrip({
  title = "Recent",
  items,
  onSeeAll,
  loading,
  empty = "Nothing made here yet.",
  size = 72,
  className,
}: {
  title?: string;
  items: RecentItem[];
  onSeeAll?: () => void;
  loading?: boolean;
  empty?: string;
  /** the side of one tile, in px */
  size?: number;
  className?: string;
}) {
  return (
    <section aria-label={title} className={cn("grid gap-2", className)} data-slot="recent-strip">
      <div className="flex items-center justify-between gap-3">
        <h3 className="m-0 font-semibold text-sm">{title}</h3>
        {onSeeAll ? (
          <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={onSeeAll}>
            See all
          </Button>
        ) : null}
      </div>
      {loading ? (
        <div className="flex gap-2 overflow-hidden">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton
              key={i}
              className="shrink-0 rounded-md"
              style={{ width: size, height: size }}
            />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="m-0 text-muted-foreground text-sm">{empty}</p>
      ) : (
        <ul className="m-0 flex list-none gap-2 overflow-x-auto p-0 pb-1">
          {items.map((item) => (
            <li key={item.id} className="shrink-0">
              <button
                type="button"
                title={item.label}
                aria-label={item.label}
                aria-current={item.current ? "true" : undefined}
                onClick={item.onOpen}
                style={{ width: size, height: size }}
                className={cn(
                  "block overflow-hidden rounded-md border bg-muted outline-none transition-[box-shadow,border-color] [&>*]:size-full [&>img]:object-cover",
                  "hover:border-primary/50 focus-visible:ring-[3px] focus-visible:ring-ring/50",
                  item.current && "border-primary ring-2 ring-primary/40",
                )}
              >
                {item.cover}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
