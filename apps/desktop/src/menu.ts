// SPDX-License-Identifier: AGPL-3.0-only
// What each item of the shared side menu opens in this window (packages/ui, `MENU_GROUPS`). An item that is
// not listed here is not built on the desktop yet and shows as "Soon".
import { type BarTab, type ItemResolver, type ItemView, placeOf } from "@wasifyai/ui";
import { type Route, newNotebook, openChat } from "./router";

/** The screen each item opens. */
export const ROUTES: Record<string, Route> = {
  "notebook.list": "notebooks",
  "images.create": "create",
  "images.edit": "edit",
  "images.reference": "reference",
  "images.inpaint": "inpaint",
  "images.library": "library",
  "video.create": "video",
  "video.animate": "animate",
  "video.extend": "extend",
  motion: "videobuilder",
  model3d: "model3d",
  "video.library": "videos",
  "voice.speak": "speak",
  "voice.transcribe": "transcribe",
  "voice.lipsync": "lipsync",
  "voice.voices": "voices",
  "voice.convert": "convert",
  "voice.edit": "speechedit",
  "voice.dub": "dub",
  "voice.audiobook": "audiobook",
  "music.create": "music",
  "music.library": "tracks",
  "music.lyrics": "lyrics",
  "music.separate": "separate",
  // the Library item is My creations, as on the web; "Your images" has its own item
  library: "creations",
  models: "models",
  train: "train",
};

/** What the window's menu does for each item, given where the person is. */
export function resolveItem(
  route: Route,
  go: (r: Route) => void,
  opts: {
    conversationId: string | null;
    notebook: string | null;
  },
): ItemResolver {
  const { conversationId, notebook } = opts;
  return (id): ItemView | undefined => {
    if (id === "chat") {
      return {
        current: route === "home" && !conversationId,
        onSelect: () => {
          openChat(null);
          go("home");
        },
      };
    }
    if (id === "notebook.create") {
      return { current: route === "notebook" && notebook === "new", onSelect: newNotebook };
    }
    if (id === "notebook.list") {
      return {
        current: route === "notebooks" || (route === "notebook" && notebook !== "new"),
        onSelect: () => go("notebooks"),
      };
    }
    const target = ROUTES[id];
    if (!target) return undefined;
    return { current: route === target, onSelect: () => go(target) };
  };
}

const OTHER_TITLES: Partial<Record<Route, string>> = {
  home: "Chat",
  notebooks: "Notebooks",
  notebook: "Notebook",
  videobuilder: "Motion graphics",
  model3d: "3D model",
  creations: "Library",
  models: "Model hub",
  train: "Train models",
  settings: "Settings",
};

/** What the top bar shows for a screen: the entry's name as the title, and the entry's tools as tabs. */
export function barFor(resolve: ItemResolver, route: Route): { title: string; tabs: BarTab[] } {
  const place = placeOf(resolve);
  if (!place) return { title: OTHER_TITLES[route] ?? "Wasify AI", tabs: [] };
  return {
    title: place.entry.label,
    tabs: place.tabs.map(({ item, view }) => ({
      id: item.id,
      label: item.label,
      current: view.current === true,
      onSelect: view.onSelect,
    })),
  };
}

/** What the top bar of the window says for a screen (the entry's name; "Settings" and the like outside the menu). */
export function routeTitle(route: Route): string {
  return barFor(
    resolveItem(route, () => {}, { conversationId: null, notebook: null }),
    route,
  ).title;
}
