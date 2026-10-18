// What each item of the shared side menu (packages/ui, `MENU_GROUPS`) opens on the web. An item that is not
// listed is not served on the web yet and shows as "Soon"; the desktop's own menu keeps the same shape
// (docs/phase3-web-parity-plan.md).
import type { ItemResolver, ItemView } from "@wasifyai/ui";
import { PRODUCTS, type Product } from "./products";
import { VOICE_SCREENS, type VoiceScreenName, voicePath } from "./voice-screens";

const live = (id: Product["id"]) => PRODUCTS.find((p) => p.id === id && p.status === "live");
const inArea = (pathname: string, href: string) =>
  pathname === href || pathname.startsWith(`${href}/`);

/** What the menu does for each item, given the page being shown. `show` is the My creations filter;
 * `served` says what this deployment offers beyond the always-on products (notebooks need a reading
 * worker and speech needs the gateway's voice aliases, so they are switched on with
 * `NOTEBOOKS_ENABLED` and `VOICE_ENABLED`). */
export function resolveWebItem(
  pathname: string,
  show: string | null,
  served: {
    notebooks?: boolean;
    voice?: boolean;
    voiceScreens?: readonly VoiceScreenName[];
  } = {},
): ItemResolver {
  // one page of a product: its create page, edit page or library (a saved result counts as the library)
  const page = (href: string, also?: string): ItemView => ({
    href,
    current: pathname === href || (also !== undefined && inArea(pathname, also)),
  });

  // a voice screen the deployment's models can run (the older pages stay where it cannot)
  const voiceScreen = (name: VoiceScreenName): ItemView | undefined =>
    served.voice && served.voiceScreens?.includes(name) ? page(voicePath(name)) : undefined;
  const byItem = new Map(
    (Object.keys(VOICE_SCREENS) as VoiceScreenName[]).map((n) => [VOICE_SCREENS[n].item, n]),
  );

  return (id) => {
    const screen = byItem.get(id);
    if (screen && id !== "voice.speak" && id !== "voice.transcribe") {
      const found = voiceScreen(screen);
      return found;
    }
    switch (id) {
      case "images.create":
        return live("image") ? page("/image") : undefined;
      case "images.edit":
        return live("image") ? page("/image/edit") : undefined;
      case "images.library":
        return live("image") ? page("/image/library", "/image/creations") : undefined;
      case "video.create":
        return live("video") ? page("/video") : undefined;
      case "video.animate":
        return live("video") ? page("/video/animate") : undefined;
      case "video.library":
        return live("video") ? page("/video/library", "/video/creations") : undefined;
      case "voice.speak":
        // with the voice product on, one screen serves both apps and the older page redirects to it
        return served.voice ? page("/voice/speak") : undefined;
      case "voice.transcribe":
        return served.voice ? page("/voice/transcribe") : undefined;
      case "notebook.create":
        return served.notebooks ? page("/notebooks/new") : undefined;
      case "notebook.list":
        return served.notebooks
          ? {
              href: "/notebooks",
              current:
                pathname === "/notebooks" ||
                (pathname.startsWith("/notebooks/") && pathname !== "/notebooks/new"),
            }
          : undefined;
      case "chat":
        return { href: "/", current: pathname === "/" }; // an open chat is marked in Recents
      case "library":
        return { href: "/creations", current: pathname === "/creations" && !show };
      case "models": // models are chosen by the deployment's admin, not by each person
        return { hidden: true };
      default:
        return undefined;
    }
  };
}
