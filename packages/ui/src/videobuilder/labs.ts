"use client";
// The Labs switch for Video Builder (ADR-0077: experimental, behind a switch): off until the person turns it on.
// The choice is a convenience kept in the webview, never required: if storage is blocked the screen stays off.
import { useCallback, useSyncExternalStore } from "react";

export const VIDEO_BUILDER_KEY = "wasifyai.labs.video-builder";
const CHANGED = "wasifyai:labs-changed";

export function readVideoBuilder(): boolean {
  try {
    return localStorage.getItem(VIDEO_BUILDER_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeVideoBuilder(on: boolean): void {
  try {
    if (on) localStorage.setItem(VIDEO_BUILDER_KEY, "1");
    else localStorage.removeItem(VIDEO_BUILDER_KEY);
  } catch {
    // forgotten
  }
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(CHANGED, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(CHANGED, cb);
    window.removeEventListener("storage", cb);
  };
}

/** Whether Video Builder is switched on, and a way to change it. The server and the first paint say no. */
export function useVideoBuilderLabs(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, readVideoBuilder, () => false);
  const set = useCallback((next: boolean) => writeVideoBuilder(next), []);
  return [on, set];
}
