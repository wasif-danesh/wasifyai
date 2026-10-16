// SPDX-License-Identifier: AGPL-3.0-only
import { cn } from "@wasifyai/ui";
import {
  AudioLines,
  BookOpen,
  ChevronDown,
  ChevronRight,
  FilePlus2,
  FileText,
  Film,
  FlaskConical,
  Image as ImageIcon,
  Library,
  type LucideIcon,
  Maximize2,
  Mic,
  Music,
  Paintbrush,
  PanelLeft,
  Pencil,
  Search,
  Settings,
  Shuffle,
  Sparkles,
  SquarePen,
  SquareStack,
  Users,
  Video,
  Volume2,
  ZoomIn,
} from "lucide-react";
import { useState } from "react";
import { useConversations } from "./conversations";
import { type Route, newNotebook, openChat } from "./router";

/** One entry of a group: a screen, an action, or something the menu keeps a place for. */
export type Leaf = {
  label: string;
  icon: LucideIcon;
  /** the screen it opens; it is the current page while that screen is open */
  route?: Route;
  /** what clicking does when it is not just opening a route */
  run?: () => void;
  /** when it counts as the current page (default: its route) */
  current?: (route: Route, notebook: string | null) => boolean;
  soon?: boolean;
};

export type GroupId = "notebook" | "images" | "video" | "voice" | "music";

export type Group = { id: GroupId; label: string; icon: LucideIcon; items: Leaf[] };

/** The groups of the side menu, in order (docs/desktop-profile.md, "The side menu's final shape").
 * Items whose product is not built on the desktop yet are listed and marked, never hidden. */
export const GROUPS: Group[] = [
  {
    id: "notebook",
    label: "Notebook",
    icon: BookOpen,
    items: [
      {
        label: "Create",
        icon: FilePlus2,
        run: newNotebook,
        current: (route, nb) => route === "notebook" && nb === "new",
      },
      {
        label: "View Notebooks",
        icon: BookOpen,
        route: "notebooks",
        current: (route, nb) => route === "notebooks" || (route === "notebook" && nb !== "new"),
      },
    ],
  },
  {
    id: "images",
    label: "Images",
    icon: ImageIcon,
    items: [
      { label: "Create", icon: Sparkles, route: "create" },
      { label: "Edit", icon: Pencil, route: "edit" },
      { label: "Transform", icon: Shuffle, soon: true },
      { label: "Inpaint", icon: Paintbrush, soon: true },
      { label: "Extend", icon: Maximize2, soon: true },
      { label: "Upscale", icon: ZoomIn, soon: true },
      { label: "Reference", icon: SquareStack, soon: true },
      { label: "Your images", icon: Library, route: "library" },
    ],
  },
  {
    id: "video",
    label: "Video",
    icon: Video,
    items: [
      { label: "Create", icon: Sparkles, soon: true },
      { label: "Animate an image", icon: Film, soon: true },
      { label: "Extend video", icon: Maximize2, soon: true },
      { label: "Your videos", icon: Library, soon: true },
    ],
  },
  {
    id: "voice",
    label: "Voice",
    icon: Volume2,
    items: [
      { label: "Text to speech", icon: Volume2, soon: true },
      { label: "Speech to text", icon: Mic, soon: true },
      { label: "Lip sync", icon: Film, soon: true },
      { label: "Voices", icon: Users, soon: true },
    ],
  },
  {
    id: "music",
    label: "Music",
    icon: Music,
    items: [
      { label: "Create", icon: Sparkles, soon: true },
      { label: "Your music", icon: Library, soon: true },
      { label: "Lyrics", icon: FileText, soon: true },
    ],
  },
];

/** The group the current page belongs to, if any. */
export function groupOf(route: Route): GroupId | null {
  if (route === "notebook" || route === "notebooks") return "notebook";
  if (route === "create" || route === "edit" || route === "library") return "images";
  return null;
}

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
  conversationId,
  notebook,
}: {
  route: Route;
  go: (r: Route) => void;
  onCollapse: () => void;
  conversationId: string | null;
  /** the notebook open, `new` for a draft */
  notebook: string | null;
}) {
  const recents = useConversations();
  // one group is open at a time; the one holding the current page stays open
  const [chosen, setChosen] = useState<GroupId | null>(groupOf(route));
  const here = groupOf(route);
  const openGroup = here ?? chosen;
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
        <span className="font-semibold text-xl tracking-tight">Wasify AI</span>
        <button
          type="button"
          aria-label="Search My creations"
          className="ms-auto rounded-md p-2 text-muted-foreground hover:bg-accent"
          onClick={() => go("library")}
        >
          <Search className="size-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mt-2 grid gap-0.5">
          <button
            type="button"
            className={cn(ITEM, active("home") && !conversationId && "bg-accent")}
            onClick={() => {
              openChat(null);
              go("home");
            }}
          >
            <SquarePen className="size-4" /> New chat
          </button>

          {GROUPS.map((g) => {
            const GroupIcon = g.icon;
            const open = openGroup === g.id;
            return (
              <div key={g.id} className="grid gap-0.5">
                <button
                  type="button"
                  aria-expanded={open}
                  className={cn(ITEM, here === g.id && "font-medium")}
                  onClick={() => setChosen(open && here !== g.id ? null : g.id)}
                >
                  <GroupIcon className="size-4" /> {g.label}
                  {open ? (
                    <ChevronDown className="ms-auto size-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="ms-auto size-4 text-muted-foreground" />
                  )}
                </button>
                {open ? (
                  <div className="grid gap-0.5 ps-3">
                    {g.items.map((t) => {
                      const Icon = t.icon;
                      const current = t.current
                        ? t.current(route, notebook)
                        : t.route
                          ? active(t.route)
                          : false;
                      return (
                        <button
                          key={t.label}
                          type="button"
                          disabled={t.soon}
                          aria-current={current ? "page" : undefined}
                          className={cn(
                            ITEM,
                            "py-1.5 text-[0.9rem]",
                            current && "bg-accent",
                            t.soon && "cursor-default opacity-60 hover:bg-transparent",
                          )}
                          onClick={() => {
                            if (t.run) t.run();
                            else if (t.route) go(t.route);
                          }}
                        >
                          <Icon className="size-4" /> {t.label}
                          {t.soon ? <Soon /> : null}
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            );
          })}

          <button
            type="button"
            className={cn(ITEM, active("library") && "bg-accent")}
            onClick={() => go("library")}
          >
            <Library className="size-4" /> Library
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
            disabled
            className={cn(ITEM, "cursor-default opacity-60 hover:bg-transparent")}
          >
            <FlaskConical className="size-4" /> Train <Soon />
          </button>
        </div>

        <div className="mt-4 px-3 text-muted-foreground text-sm">Recents</div>
        {recents.length === 0 ? (
          <div className="px-3 py-1 text-muted-foreground/80 text-sm">No chats yet</div>
        ) : (
          <ul className="grid gap-0.5" aria-label="Recent chats">
            {recents.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  title={c.title}
                  aria-current={active("home") && conversationId === c.id ? "page" : undefined}
                  className={cn(
                    ITEM,
                    "py-1.5 text-[0.9rem]",
                    active("home") && conversationId === c.id && "bg-accent",
                  )}
                  onClick={() => {
                    openChat(c.id);
                  }}
                >
                  <span className="truncate">{c.title || "New chat"}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

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
