"use client";

import { cn } from "@/lib/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** A nav link that marks itself as the current page (`aria-current`), which is also what the styling follows. */
export function NavLink({
  href,
  children,
  exact = false,
  className,
}: {
  href: string;
  children: ReactNode;
  exact?: boolean;
  className?: string;
}) {
  const path = usePathname();
  const active =
    exact || href === "/" ? path === href : path === href || path.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-control px-3 py-2 font-medium text-muted-foreground no-underline transition-colors hover:bg-accent hover:text-foreground aria-[current=page]:bg-surface aria-[current=page]:text-foreground aria-[current=page]:shadow-sm",
        className,
      )}
    >
      {children}
    </Link>
  );
}
