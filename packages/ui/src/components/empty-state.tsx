import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../cn";

/**
 * What an area shows before there is anything in it: what goes here and the first step to take
 * (`design/DESIGN.md`: "empty (says what goes here and how to start)").
 */
export function EmptyState({
  icon: Icon,
  title,
  text,
  action,
  size = "default",
  className,
}: {
  icon?: LucideIcon;
  title: string;
  text?: ReactNode;
  /** the one thing to do first, usually a `Button` */
  action?: ReactNode;
  size?: "sm" | "default";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid justify-items-center gap-2 text-center text-muted-foreground",
        size === "sm" ? "py-6" : "py-12",
        className,
      )}
      data-slot="empty-state"
    >
      {Icon ? (
        <span className="grid size-12 place-items-center rounded-full bg-muted text-muted-foreground">
          <Icon aria-hidden="true" className="size-6" />
        </span>
      ) : null}
      <h3
        className={cn("m-0 font-semibold text-foreground", size === "sm" ? "text-base" : "text-lg")}
      >
        {title}
      </h3>
      {text ? <p className="m-0 max-w-prose text-sm">{text}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
