"use client";

import { useCallback, useState } from "react";

/**
 * Where a menu or a list of choices opened from `el` must be put. Our dialogs are the browser's own
 * modal `<dialog>`, which sits in the top layer above the page: a menu put at the end of the page (a
 * portal's default) opens behind it and cannot be seen or clicked. Inside a dialog it goes into the
 * dialog; anywhere else, `undefined`, the page. Give `ref` to the button that opens it.
 */
export function useLayerHost<T extends HTMLElement>() {
  const [host, setHost] = useState<HTMLElement | undefined>(undefined);
  const ref = useCallback((el: T | null) => {
    setHost(el?.closest("dialog") ?? undefined);
  }, []);
  return [ref, host] as const;
}
