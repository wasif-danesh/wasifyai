"use client";

import { type KeyboardEvent, type PointerEvent, useCallback, useRef, useState } from "react";

const KEY = "wasifyai:studio-width";
export const STUDIO_MIN = 272;
const STUDIO_MAX = 960;
const STUDIO_WIDE = 640;
const KEY_STEP = 24;
/** What the sources list and the conversation keep, so Studio cannot push them out of the window. */
const KEPT_BESIDE = 21 * 16 + 20 * 16;

function read(): number | null {
  try {
    const v = Number(localStorage.getItem(KEY));
    return Number.isFinite(v) && v >= STUDIO_MIN ? v : null;
  } catch {
    return null;
  }
}

function write(width: number | null) {
  try {
    if (width === null) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, String(Math.round(width)));
  } catch {
    // private mode: the width is simply not remembered
  }
}

/**
 * The width of the Studio pane, which the person can drag, nudge with the arrow keys, or widen with a
 * button. `null` is the default width. It is remembered in this browser only (a per-viewer convenience).
 */
export function useStudioWidth() {
  const [width, setWidth] = useState<number | null>(read);
  const grid = useRef<HTMLDivElement>(null);
  const column = useRef<HTMLDivElement>(null);

  const limit = useCallback(() => {
    const total = grid.current?.clientWidth || STUDIO_MAX + KEPT_BESIDE; // 0: not laid out yet
    return Math.max(STUDIO_MIN, Math.min(STUDIO_MAX, total - KEPT_BESIDE));
  }, []);
  const clamp = useCallback(
    (w: number) => Math.round(Math.min(limit(), Math.max(STUDIO_MIN, w))),
    [limit],
  );
  const set = useCallback(
    (w: number | null) => {
      const next = w === null ? null : clamp(w);
      setWidth(next);
      write(next);
    },
    [clamp],
  );
  const current = () => column.current?.getBoundingClientRect().width || STUDIO_MIN;

  const wide = (width ?? 0) >= 520;
  const toggleWide = useCallback(() => set(wide ? null : STUDIO_WIDE), [set, wide]);

  const handle = {
    onPointerDown(e: PointerEvent<HTMLElement>) {
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    onPointerMove(e: PointerEvent<HTMLElement>) {
      if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
      const right = column.current?.getBoundingClientRect().right;
      if (right !== undefined) setWidth(clamp(right - e.clientX)); // the width follows the pointer
    },
    onPointerUp(e: PointerEvent<HTMLElement>) {
      if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
      e.currentTarget.releasePointerCapture(e.pointerId);
      write(width);
    },
    onKeyDown(e: KeyboardEvent<HTMLElement>) {
      if (e.key === "ArrowLeft") set(current() + KEY_STEP);
      else if (e.key === "ArrowRight") set(current() - KEY_STEP);
      else if (e.key === "Home") set(null);
      else if (e.key === "End") set(limit());
      else if (e.key === "Enter") toggleWide();
      else return;
      e.preventDefault();
    },
    onDoubleClick: toggleWide,
  };

  return { width, wide, toggleWide, handle, grid, column, min: STUDIO_MIN, max: limit };
}
