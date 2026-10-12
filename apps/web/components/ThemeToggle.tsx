"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";
const STORAGE_KEY = "wasifyai-theme";

function applyColorScheme(theme: Theme) {
  document.documentElement.style.colorScheme = theme;
  document.documentElement.dataset.theme = theme; // the dark: classes of the shadcn components follow this
  const color = theme === "dark" ? "#111214" : "#f4f3ef";
  const metaTags = document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]');
  for (let index = 0; index < metaTags.length; index += 1) {
    metaTags[index].content = color;
  }
}

function applyTheme(theme: Theme) {
  applyColorScheme(theme);
  setThemePreference(theme);
}

function setThemePreference(theme: Theme) {
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // The selected theme still applies for this session when storage is unavailable.
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    let saved: string | null = null;
    try {
      saved = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      // Fall back to the system preference when storage is unavailable.
    }

    const initial: Theme =
      saved === "light" || saved === "dark" ? saved : media.matches ? "dark" : "light";
    setTheme(initial);
    applyColorScheme(initial);

    const followSystem = (event: MediaQueryListEvent) => {
      try {
        const stored = window.localStorage.getItem(STORAGE_KEY);
        if (stored === "light" || stored === "dark") return;
      } catch {
        // If storage is unavailable, continue following the system preference.
      }
      const next: Theme = event.matches ? "dark" : "light";
      setTheme(next);
      applyColorScheme(next);
    };
    media.addEventListener("change", followSystem);
    return () => media.removeEventListener("change", followSystem);
  }, []);

  function toggle() {
    const current =
      theme ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next: Theme = current === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  }

  const nextTheme = theme ? (theme === "dark" ? "light" : "dark") : null;

  return (
    <button
      type="button"
      className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-[0.65rem] border bg-surface px-2.5 py-1.5 text-[0.82rem] font-medium whitespace-nowrap text-foreground transition-colors hover:border-primary/35 hover:bg-muted"
      onClick={toggle}
      aria-label={nextTheme ? `Switch to ${nextTheme} theme` : "Toggle light and dark theme"}
      title={nextTheme ? `Switch to ${nextTheme} theme` : "Toggle light and dark theme"}
    >
      <span className="text-base leading-none text-muted-foreground" aria-hidden="true">
        {nextTheme === null ? "◐" : nextTheme === "dark" ? "☾" : "☼"}
      </span>
      <span>{nextTheme === null ? "Theme" : nextTheme === "dark" ? "Dark" : "Light"}</span>
    </button>
  );
}
