"use client";

import { ArrowLeft } from "lucide-react";
import { type ReactNode, createContext, useContext, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "./cn";
import { Button } from "./components/button";

/** The top bar of the app window: where its content goes, and a way to say a page has put something there. */
export type WindowBar = {
  /** null until the place for it is on the screen: a page waits, then puts its header there */
  target: HTMLElement | null;
  /** A page took the bar: the window stops showing its own title. Returns the call that gives it back. */
  claim(): () => void;
};

const WindowBarContext = createContext<WindowBar | null>(null);

export function WindowBarProvider({
  bar,
  children,
}: {
  bar: WindowBar | null;
  children: ReactNode;
}) {
  return <WindowBarContext.Provider value={bar}>{children}</WindowBarContext.Provider>;
}

/**
 * A page's header: its title and its tools. In the app window they go into the top bar of the window (beside
 * the window's buttons, where the window can be dragged by them); anywhere else, such as the web, they are a
 * header of the page. Put the title first and the tools last: they are laid out as a row that spreads out.
 */
export function PageHeader({
  className,
  children,
  pageOnly,
  title,
}: {
  /** the classes of the header where there is no window bar */
  className?: string;
  children: ReactNode;
  /** tools that stay in a header of the page and are left out of the window's bar (it is kept bare for now) */
  pageOnly?: ReactNode;
  /** this header carries the screen's own title (a chat's, a notebook's): the bar then hides its own */
  title?: boolean;
}) {
  const bar = useContext(WindowBarContext);
  useEffect(() => (title ? bar?.claim() : undefined), [bar, title]);
  if (bar) return bar.target ? createPortal(children, bar.target) : null;
  return (
    <header data-tauri-drag-region className={cn(className)}>
      {children}
      {pageOnly}
    </header>
  );
}

/**
 * A top bar for a page that is not in the app window (the web): the page's header goes in a bar at the top of
 * this area, as it does in the window's own bar, so a screen puts its tools in the same place everywhere.
 * Inside the window it does nothing.
 */
export function TopBarSlot({ children }: { children: ReactNode }) {
  const outer = useContext(WindowBarContext);
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const bar = useMemo<WindowBar>(() => ({ target, claim: () => () => {} }), [target]);
  if (outer) return <>{children}</>;
  return (
    <WindowBarProvider bar={bar}>
      <div
        ref={setTarget}
        className="flex h-14 items-center gap-4 border-b px-6 empty:hidden"
        data-testid="top-bar"
      />
      {children}
    </WindowBarProvider>
  );
}

/**
 * "Back" in the bar (ADR-0093, stage U10): a screen with steps (Teach, a set, a run) leads back to its front door from
 * the top of the screen, where the window's own Back is, instead of a link under the card.
 */
export function BackInBar({ label, onBack }: { label: string; onBack: () => void }) {
  return (
    <PageHeader className="flex shrink-0 items-center px-4 pt-3">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onBack}
        aria-label={`Back to ${label}`}
      >
        <ArrowLeft aria-hidden="true" />
        {label}
      </Button>
    </PageHeader>
  );
}
