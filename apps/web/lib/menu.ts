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
 * `served` says which voice screens the deployment's models can run: a screen is linked only when a ready model can do
 * what it needs. There are no switches for products: notebooks and speech are always there. */
export function resolveWebItem(
  pathname: string,
  show: string | null,
  served: { voiceScreens?: readonly VoiceScreenName[]; isAdmin?: boolean } = {},
): ItemResolver {
  // one page of a product: its create page, edit page or library (a saved result counts as the library)
  const page = (href: string, also?: string): ItemView => ({
    href,
    current: pathname === href || (also !== undefined && inArea(pathname, also)),
  });

  // a voice screen the deployment's models can run (the older pages stay where it cannot)
  const voiceScreen = (name: VoiceScreenName): ItemView | undefined =>
    served.voiceScreens?.includes(name) ? page(voicePath(name)) : undefined;
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
      case "images.inpaint":
        return live("image") ? page("/image/inpaint") : undefined;
      case "images.reference":
        return live("image") ? page("/image/reference") : undefined;
      case "images.model3d":
        return live("image") ? page("/image/3d") : undefined;
      case "images.library":
        return live("image") ? page("/image/library", "/image/creations") : undefined;
      case "video.create":
        return live("video") ? page("/video") : undefined;
      case "video.animate":
        return live("video") ? page("/video/animate") : undefined;
      case "video.extend":
        return live("video") ? page("/video/extend") : undefined;
      case "video.builder":
        return live("video") ? page("/video/builder") : undefined;
      case "video.library":
        return live("video") ? page("/video/library", "/video/creations") : undefined;
      case "voice.speak":
        // with the voice product on, one screen serves both apps and the older page redirects to it
        return page("/voice/speak");
      case "voice.transcribe":
        return page("/voice/transcribe");
      case "notebook.create":
        return page("/notebooks/new");
      case "notebook.list":
        return {
          href: "/notebooks",
          current:
            pathname === "/notebooks" ||
            (pathname.startsWith("/notebooks/") && pathname !== "/notebooks/new"),
        };
      case "chat":
        return { href: "/", current: pathname === "/" }; // an open chat is marked in Recents
      case "library":
        return { href: "/creations", current: pathname === "/creations" && !show };
      case "models": // the models of the workers are an admin's to manage; everyone else uses the pickers
        return served.isAdmin ? page("/admin/workers", "/admin/workers") : { hidden: true };
      default:
        return undefined;
    }
  };
}
