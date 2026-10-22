import { PRODUCTS, type Product } from "./products";
import { VOICE_SCREENS, isVoiceScreen } from "./voice-screens";

/** The product pages beside Create (`/image/edit`, `/video/library`) and what the breadcrumb calls them. */
const SUBPAGES: Record<string, string> = {
  edit: "Edit",
  inpaint: "Inpaint",
  "3d": "3D model",
  reference: "Reference",
  extend: "Extend video",
  builder: "Video Builder",
  animate: "Animate a picture",
  library: "Library",
};

export type Crumb = { label: string; href?: string };

/** The product whose area a path belongs to (/video/creations/1 belongs to Video), if any. */
export function productOf(pathname: string): Product | undefined {
  return PRODUCTS.find((p) => pathname === p.href || pathname.startsWith(`${p.href}/`));
}

/** The breadcrumb for a path: where the user is, from the product down. Only the last crumb has no link. */
export function crumbs(pathname: string): Crumb[] {
  if (pathname === "/creations" || pathname.startsWith("/creations/")) {
    return [{ label: "My creations" }];
  }
  const voiceScreen = /^\/voice\/(\w+)$/.exec(pathname)?.[1];
  if (voiceScreen && isVoiceScreen(voiceScreen)) {
    const { title, item } = VOICE_SCREENS[voiceScreen];
    return [{ label: item.startsWith("music.") ? "Music" : "Voice" }, { label: title }];
  }
  if (pathname === "/notebooks") return [{ label: "Notebooks" }];
  if (pathname.startsWith("/notebooks/")) {
    return [
      { label: "Notebooks", href: "/notebooks" },
      { label: pathname === "/notebooks/new" ? "New notebook" : "Notebook" },
    ];
  }
  const product = productOf(pathname);
  if (!product) return [];
  if (pathname === product.href) return [{ label: product.title }];
  const sub = SUBPAGES[pathname.slice(product.href.length + 1)];
  if (sub) return [{ label: product.title, href: product.href }, { label: sub }];
  // /image/creations/<id>: one saved result of that product
  return [{ label: product.title, href: product.href }, { label: "Saved result" }];
}

/** Is a navigation link the current page? A product's own link matches its whole area. */
export function isCurrent(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
