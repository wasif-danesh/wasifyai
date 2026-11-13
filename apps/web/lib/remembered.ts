import type { Remembered } from "@wasifyai/ui";

/** Small choices (the model last used) and hand-offs between screens, kept in this browser. Never required. */
export const remembered: Remembered = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // forgotten
    }
  },
};
