"use client";

import type { ComponentProps } from "react";
import type { CreationsNav, Entry, MakeScreen } from "./model";

/** A link to an entry or a screen: a real address where the app has them (the web), and always handled by the app's own router. */
export function NavLink({
  nav,
  to,
  onClick,
  ...props
}: { nav: CreationsNav; to: Entry | MakeScreen } & Omit<ComponentProps<"a">, "href">) {
  return (
    <a
      {...props}
      href={nav.href?.(to) ?? "#"}
      onClick={(e) => {
        onClick?.(e);
        // a new tab or window keeps its address; anything else is the app's router
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        if (typeof to === "string") nav.make(to);
        else nav.open(to);
      }}
    />
  );
}
