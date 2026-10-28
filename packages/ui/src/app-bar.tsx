"use client";

import { Moon, Search, Sun } from "lucide-react";
import { type ReactNode, useEffect } from "react";
import { cn } from "./cn";
import { useTheme } from "./shell/theme";

/** The height of the bar, in px; on macOS the window's traffic lights are centred on it. */
export const APP_BAR_PX = 48;

/** The light-or-dark switch, in the bar on both apps. */
export function ThemeButton() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      aria-label={`Switch to the ${next} theme`}
      title={`Switch to the ${next} theme`}
      onClick={toggle}
      className="grid size-8 place-items-center rounded-md text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      {theme === "dark" ? (
        <Sun className="size-4" aria-hidden="true" />
      ) : (
        <Moon className="size-4" aria-hidden="true" />
      )}
    </button>
  );
}

/**
 * The one top bar of the app (ADR-0093 decision 1), on the desktop window and on the web: the app's navigation
 * buttons, the title of where the person is, the screen's own tools (the model button, put here by `PageHeader`),
 * then the job tray, search (⌘K) and the theme. One height everywhere; no second bar. The screens' modes stay in
 * the side menu's groups.
 */
export function AppBar({
  nav,
  navClassName,
  title,
  showTitle = true,
  slot,
  tray,
  onSearch,
  theme = true,
  drag,
  className,
}: {
  /** back, forward, the menu toggle: whatever the app puts at the start */
  nav?: ReactNode;
  /** classes for the block the nav sits in: the desktop gives it the side menu's width while the menu is open, so
   * the title starts where the panel does */
  navClassName?: string;
  title: string;
  /** false while a screen has put its own title in the slot (a chat's, a notebook's) */
  showTitle?: boolean;
  /** the place a screen's header goes: set to the element the bar gives it */
  slot?: (el: HTMLElement | null) => void;
  tray?: ReactNode;
  /** opens the search; the bar also listens for ⌘K and Ctrl+K */
  onSearch?: () => void;
  theme?: boolean;
  /** the desktop window: bare parts of the bar drag the window */
  drag?: boolean;
  className?: string;
}) {
  useEffect(() => {
    if (!onSearch) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== "k" || !(e.metaKey || e.ctrlKey) || e.altKey) return;
      e.preventDefault();
      onSearch();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onSearch]);
  const dragRegion = drag ? { "data-tauri-drag-region": true } : {};
  return (
    <header
      {...dragRegion}
      data-slot="app-bar"
      className={cn("flex shrink-0 items-center gap-2 border-b bg-card/60 pe-2", className)}
      style={{ height: APP_BAR_PX }}
    >
      {nav ? (
        <div {...dragRegion} className={cn("flex h-full shrink-0 items-center", navClassName)}>
          {nav}
        </div>
      ) : null}
      {showTitle ? (
        // where the person is, on every screen; not a heading: the screen's own h1 is the page's one heading
        <p
          {...dragRegion}
          data-slot="app-bar-title"
          className="pointer-events-none m-0 max-w-[14rem] shrink-0 truncate ps-2 font-semibold text-sm max-sm:max-w-[8rem]"
        >
          {title}
        </p>
      ) : null}
      {/* a screen's own header goes in here, as items of this row, every control at the bar's one height */}
      <div
        ref={slot}
        className="flex min-w-0 items-center gap-2 [&_[data-slot=button]]:h-8 [&_h1]:max-w-[24rem] [&_h1]:truncate [&_h1]:font-semibold [&_h1]:text-sm"
      />
      <div {...dragRegion} className="ms-auto flex shrink-0 items-center gap-1">
        {tray}
        {onSearch ? (
          <button
            type="button"
            aria-label="Search"
            aria-keyshortcuts="Control+K Meta+K"
            title="Search (⌘K)"
            onClick={onSearch}
            className="inline-flex h-8 items-center gap-2 rounded-md px-2 text-muted-foreground text-sm outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            <Search className="size-4" aria-hidden="true" />
            <span className="max-sm:sr-only">Search</span>
            <kbd className="hidden rounded border px-1 text-xs sm:inline">⌘K</kbd>
          </button>
        ) : null}
        {theme ? <ThemeButton /> : null}
      </div>
    </header>
  );
}
