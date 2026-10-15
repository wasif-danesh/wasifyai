// SPDX-License-Identifier: AGPL-3.0-only
import type { ImageSummary } from "@wasifyai/client";
import { presetOf } from "@wasifyai/ui";
import { PanelLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Sidebar } from "./Sidebar";
import { CreatePage } from "./pages/Create";
import { HomePage } from "./pages/Home";
import { LibraryPage } from "./pages/Library";
import { ModelsPage } from "./pages/Models";
import { SettingsPage } from "./pages/Settings";
import { useRoute } from "./router";

const COLLAPSED_KEY = "wasifyai:sidebar-collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

/** The window once the engine is ready: the side menu and the screen it points at. */
export function Shell() {
  const [route, go, conversationId, chatKey, adopt] = useRoute();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  // an image whose recipe was sent to Create ("make it again"); used once, then forgotten
  const [again, setAgain] = useState<ImageSummary | null>(null);
  // a result sent to Edit as its source picture ("Edit this result")
  const [editSource, setEditSource] = useState<{ url: string; name: string } | null>(null);
  useEffect(() => {
    if (route !== "create") setAgain(null);
    if (route !== "edit") setEditSource(null);
  }, [route]);
  const set = (v: boolean) => {
    setCollapsed(v);
    try {
      localStorage.setItem(COLLAPSED_KEY, v ? "1" : "0");
    } catch {
      // the menu still works; it just forgets
    }
  };

  return (
    <div className="flex h-dvh overflow-hidden bg-background text-foreground">
      {collapsed ? null : (
        <Sidebar
          route={route}
          go={go}
          onCollapse={() => set(true)}
          conversationId={conversationId}
        />
      )}
      <div className="relative flex min-w-0 flex-1 flex-col">
        <div data-tauri-drag-region className="absolute inset-x-0 top-0 z-10 h-2.5" />
        {collapsed ? (
          <button
            type="button"
            aria-label="Show the side menu"
            className="absolute start-20 top-2 z-20 rounded-md p-1.5 text-muted-foreground hover:bg-accent"
            onClick={() => set(false)}
          >
            <PanelLeft className="size-4" />
          </button>
        ) : null}
        <main id="main" className="min-h-0 flex-1 overflow-auto">
          {route === "home" ? (
            <HomePage key={chatKey} go={go} conversationId={conversationId} onAdopt={adopt} />
          ) : null}
          {route === "create" ? (
            <CreatePage
              key={`create-${again?.id ?? ""}`}
              mode="text"
              go={go}
              preset={again ? presetOf(again) : null}
              onEditThis={(image) => {
                setEditSource({ url: image.image_url, name: `${image.id}.png` });
                go("edit");
              }}
            />
          ) : null}
          {route === "edit" ? (
            <CreatePage
              key={`edit-${editSource?.url ?? ""}`}
              mode="image"
              go={go}
              source={editSource}
            />
          ) : null}
          {route === "library" ? (
            <LibraryPage
              go={go}
              onRunAgain={(image) => {
                setAgain(image);
                go("create");
              }}
            />
          ) : null}
          {route === "models" ? <ModelsPage /> : null}
          {route === "settings" ? <SettingsPage /> : null}
        </main>
      </div>
    </div>
  );
}
