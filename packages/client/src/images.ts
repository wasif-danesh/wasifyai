// A person's finished images, from the product's read routes (`/products/wasifyai-image/images`):
// list, search, open, favourite, save a copy, delete. The same routes serve the web app and the
// desktop window; only the transport differs.
import type { ImageMode } from "./image-flow";
import { HttpError, type Transport, errorMessage } from "./transport";

export const IMAGE_PRODUCT_ID = "wasifyai-image";

/** A style (LoRA) applied to an image: its name relative to a `loras` folder, and its strength. */
export type LoraChoice = { name: string; weight: number };

/** What made an image (versioned). `size` is null for an edit: it keeps the picture's own size. */
export type ImageRecipe = {
  v: number;
  mode: ImageMode;
  prompt: string;
  size: string | null;
  width: number;
  height: number;
  seed: number;
  /** absent on images made before styles existed */
  loras?: LoraChoice[];
};

export type ImageSummary = {
  id: string;
  prompt: string;
  mode: ImageMode;
  width: number;
  height: number;
  created_at: string;
  image_url: string;
  thumb_url: string;
  /** null on images made before recipes existed */
  recipe: ImageRecipe | null;
  favourite: boolean;
};

export type ImagePage = { images: ImageSummary[]; next_before: string | null };

export type ListOptions = { limit?: number; before?: string | null; favourites?: boolean };

export type ImagesApi = {
  list(options?: ListOptions): Promise<ImagePage>;
  /** Images whose words or meaning match `q`, best first (My creations search, ADR-0041). */
  search(q: string): Promise<ImageSummary[]>;
  get(id: string): Promise<ImageSummary>;
  remove(id: string): Promise<void>;
  setFavourite(id: string, favourite: boolean): Promise<ImageSummary>;
  /** Save a copy into the person's folder; only the desktop engine offers it. */
  /** Save a copy: at `path` (chosen in the system's Save As box), or into the engine's export folder. */
  exportCopy(id: string, path?: string): Promise<{ name: string; path: string }>;
};

export function createImagesApi(transport: Transport, product = IMAGE_PRODUCT_ID): ImagesApi {
  const base = `/products/${product}/images`;

  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }

  const JSON_HEADERS = { "content-type": "application/json" };

  return {
    list({ limit = 24, before, favourites } = {}) {
      const q = new URLSearchParams({ limit: String(limit) });
      if (before) q.set("before", before);
      if (favourites) q.set("favourites", "true");
      return json<ImagePage>(`${base}?${q}`);
    },

    async search(q) {
      const found = await json<{ results: { id: string }[] }>(
        `/creations/search?${new URLSearchParams({ q, kind: "image", limit: "24" })}`,
      );
      const ids = found.results.map((r) => r.id);
      if (ids.length === 0) return [];
      const page = await json<ImagePage>(`${base}?ids=${ids.join(",")}`);
      return page.images;
    },

    get: (id) => json<ImageSummary>(`${base}/${encodeURIComponent(id)}`),

    async remove(id) {
      const res = await transport.fetch(`${base}/${encodeURIComponent(id)}`, { method: "DELETE" });
      // gone already is as good as deleted
      if (!res.ok && res.status !== 404) {
        throw new HttpError(res.status, await errorMessage(res));
      }
    },

    setFavourite: (id, favourite) =>
      json<ImageSummary>(`${base}/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify({ favourite }),
      }),

    exportCopy: (id, path) =>
      json<{ name: string; path: string }>(`${base}/${encodeURIComponent(id)}/export`, {
        method: "POST",
        ...(path ? { headers: JSON_HEADERS, body: JSON.stringify({ path }) } : {}),
      }),
  };
}

/** "Today", "Yesterday" or a short date. */
export function when(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const days = Math.floor((now.getTime() - d.getTime()) / 86_400_000);
  if (days <= 0 && d.getDate() === now.getDate()) return "Today";
  if (days <= 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** A readable name for the common shapes; the raw size otherwise. */
export function sizeName(width: number, height: number): string {
  const r = width / height;
  if (Math.abs(r - 1) < 0.02) return "Square 1:1";
  if (Math.abs(r - 4 / 3) < 0.03) return "Landscape 4:3";
  if (Math.abs(r - 3 / 4) < 0.03) return "Portrait 3:4";
  if (Math.abs(r - 16 / 9) < 0.03) return "Wide 16:9";
  if (Math.abs(r - 9 / 16) < 0.03) return "Tall 9:16";
  return `${width}×${height}`;
}

/**
 * Can this image be made again exactly? Only a text image with a recipe: an edit's source picture is
 * deleted once the image is saved.
 */
export function canRunAgain(image: Pick<ImageSummary, "mode" | "recipe">): boolean {
  const r = image.recipe;
  return image.mode === "text" && r !== null && r.size !== null && Number.isInteger(r.seed);
}
