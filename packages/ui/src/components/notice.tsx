import type { ReactNode } from "react";
import { cn } from "../cn";
import { panel } from "../styles";

const ICON = { info: "i", warn: "!", error: "!", ok: "✓" } as const;
const TONE = {
  info: "border-primary/30 bg-primary/5 [--tone:var(--accent)]",
  warn: "border-warn/30 bg-warn/5 [--tone:var(--warn)]",
  error: "border-destructive/30 bg-destructive/5 [--tone:var(--danger)]",
  ok: "border-ok/30 bg-ok/5 [--tone:var(--ok)]",
} as const;

/** A message with a tone, a title and optional actions. Errors are announced to screen readers. */
export function Notice({
  tone = "info",
  title,
  children,
  actions,
  alert = tone === "error",
}: {
  tone?: keyof typeof ICON;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  /** Announce it to screen readers at once (errors always are). */
  alert?: boolean;
}) {
  return (
    <div
      className={cn(
        panel,
        "grid-cols-[auto_1fr] gap-x-[0.9rem] gap-y-[0.4rem] rounded-lg px-[1.2rem] py-4 shadow-none",
        TONE[tone],
      )}
      data-tone={tone}
      role={alert ? "alert" : "status"}
    >
      <span
        className="row-span-2 grid size-8 place-items-center rounded-full bg-(--tone)/20 font-extrabold text-(--tone)"
        aria-hidden="true"
      >
        {ICON[tone]}
      </span>
      <h3 className="text-lead font-semibold">{title}</h3>
      {children ? <p className="text-muted-foreground">{children}</p> : <span />}
      {actions ? (
        <div className="col-start-2 mt-2 flex flex-wrap items-center gap-2.5">{actions}</div>
      ) : null}
    </div>
  );
}
