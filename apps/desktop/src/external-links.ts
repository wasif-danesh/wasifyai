// SPDX-License-Identifier: AGPL-3.0-only
// The window does not open new windows, so a link that asks for one (a source under an answer, a page where a key is
// made) is handed to the shell, which opens it in the person's own browser. Only http and https; anything else is left alone.
import { invoke } from "@tauri-apps/api/core";

/** The address a click on this element would open in a new window, if it is an ordinary web address. */
export function externalAddress(el: Element | null): string | null {
  const a = el?.closest("a");
  if (!a || (a.target !== "_blank" && !a.hasAttribute("data-external"))) return null;
  try {
    const u = new URL(a.href);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

export function openExternalLinks(
  doc: Document = document,
  open = (url: string) => invoke("open_external", { url }),
) {
  const onClick = (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0) return;
    const url = externalAddress(e.target instanceof Element ? e.target : null);
    if (!url) return;
    e.preventDefault();
    void Promise.resolve(open(url)).catch(() => {});
  };
  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
}
