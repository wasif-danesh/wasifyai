"use client";

import { Moon, Search, Sun } from "lucide-react";
import { type ReactNode, useEffect } from "react";
import { cn } from "./cn";
import type { MenuLink } from "./shell/SideMenu";
import { useTheme } from "./shell/theme";

/** One mode of the screen a person is in, shown as a tab in the bar. */
export type BarTab = {
  id: string;
  label: string;
  current: boolean;
  href?: string;
  onSelect?: () => void;
};

/** The height of the bar, in px; on macOS the window's traffic lights are centred on it. */
export const APP_BAR_PX = 48;

const DefaultLink: MenuLink = ({ children, ...props }) => <a {...props}>{children}</a>;

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
 * the screen's tabs, then the job tray, search (⌘K) and the theme. One height everywhere; no second bar.
 */
export function AppBar({
  nav,
  title,
  showTitle = true,
  tabs,
  link: Link = DefaultLink,
  slot,
  tray,
  onSearch,
  theme = true,
  drag,
  className,
}: {
  /** back, forward, the menu toggle: whatever the app puts at the start */
  nav?: ReactNode;
  title: string;
  /** false while a screen has put its own title in the slot (a chat's, a notebook's) */
  showTitle?: boolean;
  tabs?: BarTab[];
  link?: MenuLink;
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
      {nav}
      {showTitle ? (
        <h1
          {...dragRegion}
          className="pointer-events-none m-0 max-w-[14rem] shrink-0 truncate font-semibold text-sm max-sm:max-w-[8rem]"
        >
          {title}
        </h1>
      ) : null}
      {/* a screen's own header goes in here, as items of this row */}
      <div ref={slot} className="contents" />
      {tabs && tabs.length > 0 ? (
        <nav aria-label="Modes" className="ms-2 min-w-0 overflow-x-auto">
          <ul className="m-0 flex list-none items-center gap-0.5 rounded-md bg-muted/60 p-0.5">
            {tabs.map((t) => {
              const look = cn(
                "inline-flex h-7 shrink-0 items-center whitespace-nowrap rounded-[0.3rem] px-2.5 font-medium text-sm no-underline outline-none transition-colors",
                t.current
                  ? "bg-surface text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
                "focus-visible:ring-[3px] focus-visible:ring-ring/50",
              );
              return (
                <li key={t.id} className="shrink-0">
                  {t.href && !t.onSelect ? (
                    <Link
                      href={t.href}
                      className={look}
                      aria-current={t.current ? "page" : undefined}
                    >
                      {t.label}
                    </Link>
                  ) : (
                    <button
                      type="button"
                      className={look}
                      aria-current={t.current ? "page" : undefined}
                      onClick={t.onSelect}
                    >
                      {t.label}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </nav>
      ) : null}
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
