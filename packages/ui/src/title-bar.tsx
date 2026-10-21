"use client";

// The top bar of the window: one row across both panels. On the left, beside the window's own buttons (the
// traffic lights on macOS), go back, go forward and hide or show the side menu; on the right, the title of the
// screen and its tools (a screen puts them here with `PageHeader`). It is tinted like the side menu, a little
// lighter than the page, and the window can be dragged by any bare part of it.
import { ArrowLeft, ArrowRight, PanelLeft } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";

// the overlay title bar (and its traffic lights) exists on macOS only
const MAC = typeof navigator !== "undefined" && /Mac/.test(navigator.userAgent);

/** The height of the bar; the traffic lights are centred on it (`trafficLightPosition` in tauri.conf.json). */
export const TITLE_BAR_PX = 36;

function Tool({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="grid size-7 place-items-center rounded-md text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
    >
      {children}
    </button>
  );
}

export function TitleBar({
  menuOpen,
  onToggleMenu,
  canGoBack,
  canGoForward,
  title,
  showTitle,
  slot,
}: {
  menuOpen: boolean;
  onToggleMenu: () => void;
  canGoBack: boolean;
  canGoForward: boolean;
  /** what the bar says when the screen gives no title of its own */
  title: string;
  showTitle: boolean;
  /** the place a screen's header goes: set to the element the bar gives it */
  slot: (el: HTMLElement | null) => void;
}) {
  return (
    <div
      data-tauri-drag-region
      className="flex shrink-0 items-center border-b bg-card/60"
      style={{ height: TITLE_BAR_PX }}
    >
      <div
        data-tauri-drag-region
        className={cn(
          "flex h-full items-center gap-0.5 pe-2",
          MAC ? "ps-[84px]" : "ps-3",
          menuOpen && "w-64 shrink-0 border-e",
        )}
      >
        <Tool label="Back" disabled={!canGoBack} onClick={() => window.history.back()}>
          <ArrowLeft className="size-4" />
        </Tool>
        <Tool label="Forward" disabled={!canGoForward} onClick={() => window.history.forward()}>
          <ArrowRight className="size-4" />
        </Tool>
        <Tool label={menuOpen ? "Hide the side menu" : "Show the side menu"} onClick={onToggleMenu}>
          <PanelLeft className="size-4" />
        </Tool>
      </div>
      <div
        data-tauri-drag-region
        className="flex h-full min-w-0 flex-1 items-center justify-between gap-3 ps-4 pe-3"
      >
        {showTitle ? (
          <span className="pointer-events-none min-w-0 truncate font-medium text-sm">{title}</span>
        ) : null}
        {/* a screen's own header goes in here, as items of this row */}
        <div ref={slot} className="contents" />
      </div>
    </div>
  );
}
