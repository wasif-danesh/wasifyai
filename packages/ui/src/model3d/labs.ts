"use client";
// The Labs switch for 3D models (ADR-0080: experimental until the person turns it on). Like the Video
// Builder's: a convenience kept in the webview, never required; if storage is blocked it stays off.
import { useCallback, useSyncExternalStore } from "react";

export const MODEL3D_KEY = "wasifyai.labs.model3d";
const CHANGED = "wasifyai:labs-changed";

export function readModel3d(): boolean {
  try {
    return localStorage.getItem(MODEL3D_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeModel3d(on: boolean): void {
  try {
    if (on) localStorage.setItem(MODEL3D_KEY, "1");
    else localStorage.removeItem(MODEL3D_KEY);
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

/** Whether 3D models are switched on, and a way to change it. The server and the first paint say no. */
export function useModel3dLabs(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, readModel3d, () => false);
  const set = useCallback((next: boolean) => writeModel3d(next), []);
  return [on, set];
}
