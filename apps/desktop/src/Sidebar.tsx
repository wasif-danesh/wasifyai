// SPDX-License-Identifier: AGPL-3.0-only
import { cn } from "@wasifyai/ui";
import {
  ChevronDown,
  ChevronRight,
  FlaskConical,
  Image as ImageIcon,
  Library,
  type LucideIcon,
  Maximize2,
  Paintbrush,
  PanelLeft,
  Pencil,
  Search,
  Settings,
  Shuffle,
  Sparkles,
  SquarePen,
  SquareStack,
  ZoomIn,
} from "lucide-react";
import { useState } from "react";
import type { Route } from "./router";

type Leaf = { label: string; icon: LucideIcon; route?: Route; soon?: boolean };

/** The image tools. Create and Edit work today; the others are listed, as in ADR-0056 decision 10. */
export const IMAGE_TOOLS: Leaf[] = [
  { label: "Create", icon: Sparkles, route: "create" },
  { label: "Edit", icon: Pencil, route: "edit" },
  { label: "Transform", icon: Shuffle, soon: true },
  { label: "Inpaint", icon: Paintbrush, soon: true },
  { label: "Extend", icon: Maximize2, soon: true },
  { label: "Upscale", icon: ZoomIn, soon: true },
  { label: "Reference", icon: SquareStack, soon: true },
];

const ITEM =
  "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-[0.95rem] outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring";

function Soon() {
  return (
    <span className="ms-auto rounded-full border px-2 py-0.5 text-[0.65rem] text-muted-foreground uppercase tracking-wide">
      Soon
    </span>
  );
}

// the overlay title bar (and its traffic lights) exists on macOS only
const MAC = typeof navigator !== "undefined" && /Mac/.test(navigator.userAgent);

export function Sidebar({
  route,
  go,
  onCollapse,
}: {
  route: Route;
  go: (r: Route) => void;
  onCollapse: () => void;
}) {
  const inImages = route === "create" || route === "edit";
  const [imagesOpen, setImagesOpen] = useState(inImages);
  const open = imagesOpen || inImages;
  const active = (r: Route) => route === r;

  return (
    <nav
      aria-label="Main"
      className="flex h-full w-64 shrink-0 flex-col gap-1 border-e bg-card/60 px-3 pt-3 pb-3"
    >
      {/* room for the window's traffic-light buttons, and a place to drag the window by */}
      <div data-tauri-drag-region className={cn("flex h-10 items-center gap-1", MAC && "ps-20")}>
        <button
          type="button"
          aria-label="Hide the side menu"
          className="rounded-md p-1.5 text-muted-foreground hover:bg-accent"
          onClick={onCollapse}
        >
          <PanelLeft className="size-4" />
        </button>
      </div>

      <div className="flex items-center gap-2 px-2 py-2">
        <span
          aria-hidden="true"
          className="grid size-9 place-items-center rounded-full bg-primary font-bold text-lg text-primary-foreground"
        >
          w
        </span>
        <span className="font-semibold text-xl tracking-tight">wasifyai</span>
        <button
          type="button"
          aria-label="Search My creations"
          className="ms-auto rounded-md p-2 text-muted-foreground hover:bg-accent"
          onClick={() => go("library")}
        >
          <Search className="size-4" />
        </button>
      </div>

      <div className="mt-2 grid gap-0.5">
        <button
          type="button"
          className={cn(ITEM, active("home") && "bg-accent")}
          onClick={() => go("home")}
        >
          <SquarePen className="size-4" /> New chat
        </button>
        <button
          type="button"
          className={cn(ITEM, active("models") && "bg-accent")}
          onClick={() => go("models")}
        >
          <SquareStack className="size-4" /> Models
        </button>
        <button
          type="button"
          className={cn(ITEM, active("library") && "bg-accent")}
          onClick={() => go("library")}
        >
          <Library className="size-4" /> Library
        </button>

        <button
          type="button"
          aria-expanded={open}
          className={cn(ITEM, inImages && "font-medium")}
          onClick={() => {
            setImagesOpen(!open);
            if (!open) go("create");
          }}
        >
          <ImageIcon className="size-4" /> Images
          {open ? (
            <ChevronDown className="ms-auto size-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="ms-auto size-4 text-muted-foreground" />
          )}
        </button>
        {open ? (
          <div className="grid gap-0.5 ps-3">
            {IMAGE_TOOLS.map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.label}
                  type="button"
                  disabled={t.soon}
                  aria-current={t.route && active(t.route) ? "page" : undefined}
                  className={cn(
                    ITEM,
                    "py-1.5 text-[0.9rem]",
                    t.route && active(t.route) && "bg-accent",
                    t.soon && "cursor-default opacity-60 hover:bg-transparent",
                  )}
                  onClick={() => t.route && go(t.route)}
                >
                  <Icon className="size-4" /> {t.label}
                  {t.soon ? <Soon /> : null}
                </button>
              );
            })}
          </div>
        ) : null}

        <button
          type="button"
          disabled
          className={cn(ITEM, "cursor-default opacity-60 hover:bg-transparent")}
        >
          <FlaskConical className="size-4" /> Train <Soon />
        </button>
      </div>

      <div className="mt-4 px-3 text-muted-foreground text-sm">Projects</div>
      <div className="px-3 py-1 text-muted-foreground/80 text-sm">No projects</div>
      <div className="mt-3 px-3 text-muted-foreground text-sm">Recents</div>
      <div className="px-3 py-1 text-muted-foreground/80 text-sm">No chats yet</div>

      <div className="mt-auto flex items-center gap-3 px-2 pt-3">
        <span
          aria-hidden="true"
          className="grid size-9 place-items-center rounded-full bg-primary font-semibold text-primary-foreground"
        >
          Y
        </span>
        <div className="min-w-0 leading-tight">
          <div className="truncate font-medium">You</div>
          <div className="truncate text-muted-foreground text-xs">On this computer</div>
        </div>
        <button
          type="button"
          aria-label="Settings"
          aria-current={active("settings") ? "page" : undefined}
          className={cn(
            "ms-auto rounded-md p-2 text-muted-foreground hover:bg-accent",
            active("settings") && "bg-accent",
          )}
          onClick={() => go("settings")}
        >
          <Settings className="size-5" />
        </button>
      </div>
    </nav>
  );
}
