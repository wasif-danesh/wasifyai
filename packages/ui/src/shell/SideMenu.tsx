"use client";

import { ChevronDown, ChevronRight, Search } from "lucide-react";
import { type ComponentType, type ReactNode, useState } from "react";
import { cn } from "../cn";
import { CHAT_ITEM, EXTRA_ITEMS, type ItemResolver, MENU_GROUPS, type MenuItemDef } from "./menu";

/** How an app draws a link to one of its addresses (the web app passes its router's link). */
export type MenuLink = ComponentType<{
  href: string;
  className?: string;
  "aria-current"?: "page";
  children: ReactNode;
}>;

const DefaultLink: MenuLink = ({ children, ...props }) => <a {...props}>{children}</a>;

export type Recents = {
  label?: string;
  empty?: string;
  items: { id: string; title: string; current?: boolean; onSelect: () => void }[];
};

export type SideMenuProps = {
  /** What each item opens in this app. */
  resolve: ItemResolver;
  /** The app's link component; plain anchors by default. */
  link?: MenuLink;
  /** The top row above the brand: the desktop's window buttons. */
  header?: ReactNode;
  /** Where the brand goes when it is clicked (the web's home page); left out, it is plain text. */
  brandHref?: string;
  /** The brand row's search button (opens the library). Left out, no button. */
  onSearch?: () => void;
  /** Recent chats; left out, the section is not shown. */
  recents?: Recents;
  /** Items after the library, models and train: Admin on the web. */
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

/** The side menu both apps show: the brand, a chat entry, the groups (one open at a time, the one holding the
 * current page stays open), the library, and the person at the bottom. The frame around it (width, border,
 * collapsing) belongs to the app. */
export function SideMenu({
  resolve,
  link: Link = DefaultLink,
  header,
  brandHref,
  onSearch,
  recents,
  extra,
  footer,
  label = "Main",
}: SideMenuProps) {
  // what the person opened or closed by hand, and the group of the page they were on when they did
  const [chosen, setChosen] = useState<{ id: string | null; page: string | null } | null>(null);
  const hereGroup =
    MENU_GROUPS.find((g) =>
      g.items.some((i) => {
        const v = resolve(i.id);
        return v !== undefined && !("hidden" in v) && v.current;
      }),
    )?.id ?? null;
  // moving to a page of another group opens that group again; within a group the person's choice stays
  const openGroup = chosen && chosen.page === hereGroup ? chosen.id : hereGroup;

  function entry(item: MenuItemDef, small: boolean) {
    const view = resolve(item.id);
    if (view && "hidden" in view) return null;
    const Icon = item.icon;
    const soon = view === undefined;
    const current = !soon && view.current === true;
    const className = cn(
      ITEM,
      small && "py-1.5 text-ui",
      current && "bg-accent",
      soon && "cursor-default opacity-60 hover:bg-transparent",
    );
    const body = (
      <>
        <Icon className="size-4" aria-hidden="true" /> {item.label}
        {soon ? <Soon /> : null}
      </>
    );
    if (soon) {
      return (
        <button key={item.id} type="button" disabled className={className}>
          {body}
        </button>
      );
    }
    if (view.href && !view.onSelect) {
      return (
        <Link
          key={item.id}
          href={view.href}
          className={className}
          aria-current={current ? "page" : undefined}
        >
          {body}
        </Link>
      );
    }
    return (
      <button
        key={item.id}
        type="button"
        aria-current={current ? "page" : undefined}
        className={className}
        onClick={view.onSelect}
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
        {onSearch ? (
          <button
            type="button"
            aria-label="Search My creations"
            className="ms-auto rounded-md p-2 text-muted-foreground hover:bg-accent"
            onClick={onSearch}
          >
            <Search className="size-4" />
          </button>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mt-2 grid gap-0.5">
          {entry(CHAT_ITEM, false)}

          {MENU_GROUPS.map((g) => {
            const GroupIcon = g.icon;
            const open = openGroup === g.id;
            return (
              <div key={g.id} className="grid gap-0.5">
                <button
                  type="button"
                  aria-expanded={open}
                  className={cn(ITEM, hereGroup === g.id && "font-medium")}
                  onClick={() => setChosen({ id: open ? null : g.id, page: hereGroup })}
                >
                  <GroupIcon className="size-4" aria-hidden="true" /> {g.label}
                  {open ? (
                    <ChevronDown className="ms-auto size-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="ms-auto size-4 text-muted-foreground" />
                  )}
                </button>
                {open ? (
                  <div className="grid gap-0.5 ps-3">{g.items.map((i) => entry(i, true))}</div>
                ) : null}
              </div>
            );
          })}

          {EXTRA_ITEMS.map((i) => entry(i, false))}
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

        {recents ? (
          <>
            <div className="mt-4 px-3 text-muted-foreground text-sm">
              {recents.label ?? "Recents"}
            </div>
            {recents.items.length === 0 ? (
              <div className="px-3 py-1 text-muted-foreground/80 text-sm">
                {recents.empty ?? "No chats yet"}
              </div>
            ) : (
              <ul className="grid gap-0.5" aria-label="Recent chats">
                {recents.items.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      title={c.title}
                      aria-current={c.current ? "page" : undefined}
                      className={cn(ITEM, "py-1.5 text-ui", c.current && "bg-accent")}
                      onClick={c.onSelect}
                    >
                      <span className="truncate">{c.title || "New chat"}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : null}
      </div>

      {footer ? <div className="mt-auto pt-3">{footer}</div> : null}
    </nav>
  );
}
