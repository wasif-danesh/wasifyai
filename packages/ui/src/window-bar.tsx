"use client";

import { type ReactNode, createContext, useContext, useEffect } from "react";
import { createPortal } from "react-dom";
import { cn } from "./cn";

/** The top bar of the app window: where its content goes, and a way to say a page has put something there. */
export type WindowBar = {
  target: HTMLElement;
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
}: {
  /** the classes of the header where there is no window bar */
  className?: string;
  children: ReactNode;
  /** tools that stay in a header of the page and are left out of the window's bar (it is kept bare for now) */
  pageOnly?: ReactNode;
}) {
  const bar = useContext(WindowBarContext);
  useEffect(() => bar?.claim(), [bar]);
  if (bar) return createPortal(children, bar.target);
  return (
    <header data-tauri-drag-region className={cn(className)}>
      {children}
      {pageOnly}
    </header>
  );
}
