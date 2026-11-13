"use client";

import { useCallback, useEffect, useState } from "react";
import { themeColor } from "../tokens.gen";

export type Theme = "light" | "dark";
const STORAGE_KEY = "wasifyai-theme";
/** said when the theme is changed, so every place that shows it (the bar's button, Settings) follows */
const CHANGED = "wasifyai-theme-changed";

function apply(theme: Theme) {
  document.documentElement.style.colorScheme = theme;
  document.documentElement.dataset.theme = theme; // the dark: variant of the tokens follows this
  const metas = document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]');
  for (let i = 0; i < metas.length; i += 1) {
    const meta = metas[i];
    if (meta) meta.content = themeColor[theme];
  }
}

function saved(): Theme | null {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

/**
 * The theme: the system's until the person picks one, then theirs, remembered in this browser or window. The
 * same on the web and in the desktop window (the window's CSS reads `data-theme` too).
 */
export function useTheme(): {
  theme: Theme | null;
  toggle: () => void;
  /** the person's choice: "light", "dark", or null to follow the system again */
  chosen: Theme | null;
  choose: (theme: Theme | null) => void;
} {
  const [theme, setTheme] = useState<Theme | null>(null);
  const [chosen, setChosen] = useState<Theme | null>(null);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const initial = saved() ?? (media.matches ? "dark" : "light");
    setTheme(initial);
    setChosen(saved());
    if (saved()) apply(initial);
    const follow = (e: MediaQueryListEvent) => {
      if (saved()) return;
      const next: Theme = e.matches ? "dark" : "light";
      setTheme(next);
    };
    media.addEventListener("change", follow);
    const sync = () => {
      setTheme(saved() ?? (media.matches ? "dark" : "light"));
      setChosen(saved());
    };
    window.addEventListener(CHANGED, sync);
    return () => {
      media.removeEventListener("change", follow);
      window.removeEventListener(CHANGED, sync);
    };
  }, []);
  const toggle = useCallback(() => {
    const current =
      theme ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next: Theme = current === "dark" ? "light" : "dark";
    setTheme(next);
    setChosen(next);
    apply(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // it still applies for this session
    }
    window.dispatchEvent(new Event(CHANGED));
  }, [theme]);
  const choose = useCallback((next: Theme | null) => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const shown: Theme = next ?? (media.matches ? "dark" : "light");
    try {
      if (next) window.localStorage.setItem(STORAGE_KEY, next);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // it still applies for this session
    }
    setChosen(next);
    setTheme(shown);
    apply(shown);
    window.dispatchEvent(new Event(CHANGED));
  }, []);
  return { theme, toggle, chosen, choose };
}
