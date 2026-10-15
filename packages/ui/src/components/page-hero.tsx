import type { ReactNode } from "react";
import { cn } from "../cn";

/** The heading block at the top of a product page: a big title, an optional accent word, a lead line. */
export function PageHero({
  title,
  children,
  eyebrow,
  icon,
  className,
}: {
  title: ReactNode;
  children?: ReactNode;
  eyebrow?: string;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("grid gap-3 pb-2", className)}>
      {icon}
      {eyebrow ? (
        <span className="text-[0.72rem] font-bold tracking-[0.13em] text-primary uppercase">
          {eyebrow}
        </span>
      ) : null}
      <h1 className="text-step-3 leading-[1.05] font-[680] tracking-[-0.035em]">{title}</h1>
      {children ? (
        <p className="max-w-[40rem] text-step-1 leading-[1.45] text-muted-foreground">{children}</p>
      ) : null}
    </header>
  );
}

/** The coloured word inside a hero title. */
export function Accent({ children }: { children: ReactNode }) {
  return <span className="text-primary">{children}</span>;
}
