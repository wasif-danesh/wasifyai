"use client";

import type { ComponentType, ReactNode } from "react";
import { cn } from "../cn";
import { RecentChats, type Recents } from "./RecentChats";
import {
  type ItemResolver,
  type ItemView,
  MENU_ENTRIES,
  type MenuEntryDef,
  type MenuItemDef,
} from "./menu";

/** How an app draws a link to one of its addresses (the web app passes its router's link). */
export type MenuLink = ComponentType<{
  href: string;
  className?: string;
  "aria-current"?: "page";
  children: ReactNode;
}>;

const DefaultLink: MenuLink = ({ children, ...props }) => <a {...props}>{children}</a>;

export type SideMenuProps = {
  /** What each item opens in this app. */
  resolve: ItemResolver;
  /** The app's link component; plain anchors by default. */
  link?: MenuLink;
  /** The top row above the brand: the desktop's window buttons. */
  header?: ReactNode;
  /** Where the brand goes when it is clicked (the web's home page); left out, it is plain text. */
  brandHref?: string;
  /** Recent chats; left out, the section is not shown. */
  recents?: Recents;
  /** Items after the entries: Explore and Admin on the web. */
  extra?: {
    id: string;
    label: string;
    icon: MenuItemDef["icon"];
    href?: string;
    current?: boolean;
  }[];
  /** The bottom of the menu: the person and their settings. */
  footer?: ReactNode;
  /** The label of the menu for assistive technology. */
  label?: string;
};

const ITEM =
  "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-ui-lg outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring";

function Soon() {
  return (
    <span className="ms-auto rounded-full border px-2 py-0.5 text-2xs text-muted-foreground uppercase tracking-wide">
      Soon
    </span>
  );
}

type Served = { item: MenuItemDef; view: Exclude<ItemView, { hidden: true }> };

/** The items of an entry this app serves, in order; empty means the entry shows as Soon. */
function served(entry: MenuEntryDef, resolve: ItemResolver): Served[] {
  return entry.items.flatMap((item) => {
    const view = resolve(item.id);
    return view && !("hidden" in view) ? [{ item, view }] : [];
  });
}

/**
 * The side menu both apps show (ADR-0093, stage U2): the brand, eleven entries that each open a tool with one
 * click (a product's modes are tabs in the top bar), the extra items an app adds, the recent chats and the person
 * at the bottom. The frame around it (width, border, collapsing) belongs to the app.
 */
export function SideMenu({
  resolve,
  link: Link = DefaultLink,
  header,
  brandHref,
  recents,
  extra,
  footer,
  label = "Main",
}: SideMenuProps) {
  function entry(def: MenuEntryDef) {
    const views = served(def, resolve);
    // hidden on purpose (Models for a person who is not an admin on the web): not shown at all
    if (
      views.length === 0 &&
      def.items.every((i) => resolve(i.id) && "hidden" in (resolve(i.id) as object))
    )
      return null;
    const Icon = def.icon;
    const soon = views.length === 0;
    const current = views.some((v) => v.view.current);
    // the entry opens its first tool, or stays on the tool that is open
    const target = views.find((v) => v.view.current) ?? views[0];
    const className = cn(
      ITEM,
      current && "bg-accent font-medium",
      soon && "cursor-default opacity-60 hover:bg-transparent",
    );
    const body = (
      <>
        <Icon className="size-4" aria-hidden="true" /> {def.label}
        {soon ? <Soon /> : null}
      </>
    );
    if (soon || !target) {
      return (
        <button key={def.id} type="button" disabled className={className}>
          {body}
        </button>
      );
    }
    if (target.view.href && !target.view.onSelect) {
      return (
        <Link
          key={def.id}
          href={target.view.href}
          className={className}
          aria-current={current ? "page" : undefined}
        >
          {body}
        </Link>
      );
    }
    return (
      <button
        key={def.id}
        type="button"
        aria-current={current ? "page" : undefined}
        className={className}
        onClick={target.view.onSelect}
      >
        {body}
      </button>
    );
  }

  const brand = (
    <>
      <span
        aria-hidden="true"
        className="grid size-9 place-items-center rounded-full bg-primary font-bold text-lg text-primary-foreground"
      >
        w
      </span>
      <span className="font-semibold text-xl tracking-tight">Wasify AI</span>
    </>
  );

  return (
    <nav aria-label={label} className="flex h-full min-h-0 flex-col gap-1 px-3 pt-3 pb-3">
      {header}

      <div className="flex items-center gap-2 px-2 py-2">
        {brandHref ? (
          <Link
            href={brandHref}
            aria-label="Wasify AI, home"
            className="flex items-center gap-2 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {brand}
          </Link>
        ) : (
          <span className="flex items-center gap-2">{brand}</span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <div className="mt-2 grid gap-0.5">
          {MENU_ENTRIES.map(entry)}
          {(extra ?? []).map((x) => {
            const Icon = x.icon;
            const className = cn(ITEM, x.current && "bg-accent");
            return (
              <Link
                key={x.id}
                href={x.href ?? "#"}
                className={className}
                aria-current={x.current ? "page" : undefined}
              >
                <Icon className="size-4" aria-hidden="true" /> {x.label}
              </Link>
            );
          })}
        </div>

        {recents ? <RecentChats recents={recents} /> : null}
      </div>

      {footer ? <div className="mt-auto pt-3">{footer}</div> : null}
    </nav>
  );
}
