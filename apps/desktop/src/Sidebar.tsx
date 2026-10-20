// SPDX-License-Identifier: AGPL-3.0-only
// The window's side menu: the shared menu (packages/ui) in this window's frame, with what each item opens
// (`menu.ts`), the recent chats, and the person and settings at the bottom.
import { SideMenu, cn, useConversations, useVideoBuilderLabs } from "@wasifyai/ui";
import { PanelLeft, Settings } from "lucide-react";
import { assistantApi } from "./api";
import { resolveItem } from "./menu";
import { type Route, openChat } from "./router";

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
  const recents = useConversations(assistantApi);
  const [videoBuilder] = useVideoBuilderLabs();
  return (
    <div className="h-full w-64 shrink-0 border-e bg-card/60">
      <SideMenu
        resolve={resolveItem(route, go, { conversationId, notebook, videoBuilder })}
        onSearch={() => go("library")}
        header={
          // room for the window's traffic-light buttons (the start padding), a place to drag the window by, and the
          // hide button at the end of the row, next to the page title across the divider
          <div
            data-tauri-drag-region
            className={cn("flex h-10 items-center justify-end gap-1 pe-2", MAC && "ps-20")}
          >
            <button
              type="button"
              aria-label="Hide the side menu"
              className="rounded-md p-1.5 text-muted-foreground hover:bg-accent"
              onClick={onCollapse}
            >
              <PanelLeft className="size-4" />
            </button>
          </div>
        }
        recents={{
          items: recents.map((c) => ({
            id: c.id,
            title: c.title,
            current: route === "home" && conversationId === c.id,
            onSelect: () => openChat(c.id),
          })),
        }}
        footer={
          <div className="flex items-center gap-3 px-2">
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
              aria-current={route === "settings" ? "page" : undefined}
              className={cn(
                "ms-auto rounded-md p-2 text-muted-foreground hover:bg-accent",
                route === "settings" && "bg-accent",
              )}
              onClick={() => go("settings")}
            >
              <Settings className="size-5" />
            </button>
          </div>
        }
      />
    </div>
  );
}
