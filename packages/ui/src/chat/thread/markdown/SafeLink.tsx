"use client";

import type { ReactNode } from "react";

/** The base the sanitiser resolves a relative address against. Anything that comes back with this origin was relative, which a model's
 * answer has no business doing: it is shown as text, not made a link. */
export const RELATIVE_ORIGIN = "http://relative.invalid";

/** Only an absolute http(s) address is a link, and it opens in a new tab without handing the page over (`noopener noreferrer`). */
export function isSafeHref(href: string | undefined): boolean {
  try {
    const u = new URL(href ?? "");
    return (u.protocol === "https:" || u.protocol === "http:") && u.origin !== RELATIVE_ORIGIN;
  } catch {
    return false;
  }
}

export function SafeLink({ href, children }: { href?: string; children?: ReactNode }) {
  return isSafeHref(href) ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="break-words font-medium text-primary underline underline-offset-4"
    >
      {children}
    </a>
  ) : (
    <span data-link-blocked="">{children}</span>
  );
}
