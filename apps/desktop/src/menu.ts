// SPDX-License-Identifier: AGPL-3.0-only
// What each item of the shared side menu opens in this window (packages/ui, `MENU_GROUPS`). An item that is
// not listed here is not built on the desktop yet and shows as "Soon".
import type { ItemResolver, ItemView } from "@wasifyai/ui";
import { type Route, newNotebook, openChat } from "./router";

/** The screen each item opens. */
export const ROUTES: Record<string, Route> = {
  "notebook.list": "notebooks",
  "images.create": "create",
  "images.edit": "edit",
  "images.library": "library",
  "video.create": "video",
  "video.animate": "animate",
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
  library: "library",
  models: "models",
};

/** What the window's menu does for each item, given where the person is. */
export function resolveItem(
  route: Route,
  go: (r: Route) => void,
  opts: { conversationId: string | null; notebook: string | null },
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
