"use client";

import { useCallback, useEffect, useState } from "react";
import { themeColor } from "../tokens.gen";

export type Theme = "light" | "dark";
const STORAGE_KEY = "wasifyai-theme";

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
export function useTheme(): { theme: Theme | null; toggle: () => void } {
  const [theme, setTheme] = useState<Theme | null>(null);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const initial = saved() ?? (media.matches ? "dark" : "light");
    setTheme(initial);
    if (saved()) apply(initial);
    const follow = (e: MediaQueryListEvent) => {
      if (saved()) return;
      const next: Theme = e.matches ? "dark" : "light";
      setTheme(next);
    };
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, []);
  const toggle = useCallback(() => {
    const current =
      theme ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next: Theme = current === "dark" ? "light" : "dark";
    setTheme(next);
    apply(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // it still applies for this session
    }
  }, [theme]);
  return { theme, toggle };
}
