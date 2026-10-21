// SPDX-License-Identifier: AGPL-3.0-only
// The window's side menu: the shared menu (packages/ui) in this window's frame, with what each item opens
// (`menu.ts`), the recent chats, and the person and settings at the bottom.
import { SideMenu, cn, useConversations } from "@wasifyai/ui";
import { Settings } from "lucide-react";
import { assistantApi } from "./api";
import { resolveItem } from "./menu";
import { type Route, openChat } from "./router";

export function Sidebar({
  route,
  go,
  conversationId,
  notebook,
}: {
  route: Route;
  go: (r: Route) => void;
  conversationId: string | null;
  /** the notebook open, `new` for a draft */
  notebook: string | null;
}) {
  const recents = useConversations(assistantApi);
  return (
    <div className="h-full w-64 shrink-0 border-e bg-card/60">
      <SideMenu
        resolve={resolveItem(route, go, { conversationId, notebook })}
        onSearch={() => go("library")}
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
