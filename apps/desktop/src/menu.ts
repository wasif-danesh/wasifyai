// SPDX-License-Identifier: AGPL-3.0-only
// What each item of the shared side menu opens in this window (packages/ui, `MENU_GROUPS`). An item that is
// not listed here is not built on the desktop yet and shows as "Soon".
import { type ItemResolver, type ItemView, titleOf } from "@wasifyai/ui";
import { type Route, newNotebook, openChat } from "./router";

/** The screen each item opens. */
export const ROUTES: Record<string, Route> = {
  "notebook.list": "notebooks",
  "images.create": "create",
  "images.edit": "edit",
  "images.reference": "reference",
  "images.inpaint": "inpaint",
  "video.create": "video",
  "video.animate": "animate",
  "video.extend": "extend",
  creative: "creative",
  motion: "videobuilder",
  model3d: "model3d",
  "voice.speak": "speak",
  "voice.transcribe": "transcribe",
  "voice.lipsync": "lipsync",
  "voice.voices": "voices",
  "voice.convert": "convert",
  "voice.edit": "speechedit",
  "voice.dub": "dub",
  "voice.audiobook": "audiobook",
  "music.create": "music",
  "music.lyrics": "lyrics",
  "music.separate": "separate",
  // the Library item is the one Library (ADR-0093, U8), as on the web
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
    // the old "Your …" screens open the Library, filtered: the Library is the item marked there
    const library = id === "library" && LIBRARY_ROUTES.has(route);
    return { current: route === target || library, onSelect: () => go(target) };
  };
}

/** The routes that were "Your images", "Your videos" and "Your music": each opens the Library, filtered. */
export const LIBRARY_ROUTES: ReadonlySet<Route> = new Set<Route>(["library", "videos", "tracks"]);

const OTHER_TITLES: Partial<Record<Route, string>> = {
  home: "Chat",
  notebooks: "Notebooks",
  notebook: "Notebook",
  creative: "Creative Studio",
  videobuilder: "Motion graphics",
  model3d: "3D model",
  creations: "Library",
  library: "Library",
  videos: "Library",
  tracks: "Library",
  models: "Model hub",
  train: "Train models",
  settings: "Settings",
};

/** What the top bar of the window says for a screen (its group's name; "Settings" and the like outside the menu). */
export function routeTitle(route: Route): string {
  return titleFor(
    resolveItem(route, () => {}, { conversationId: null, notebook: null }),
    route,
  );
}

/** The bar's title for a screen: its menu group's name, or the screen's own outside the menu. */
export function titleFor(resolve: ItemResolver, route: Route): string {
  return titleOf(resolve) ?? OTHER_TITLES[route] ?? "Wasify AI";
}
