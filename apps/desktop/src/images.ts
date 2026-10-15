// SPDX-License-Identifier: AGPL-3.0-only
// The user's images, from the engine's product routes (the same ones the web app reads).
import { HttpError } from "@wasifyai/client";
import { transport } from "./api";

export const PRODUCT = "wasifyai-image";

export type ImageSummary = {
  id: string;
  prompt: string;
  mode: "text" | "image";
  width: number;
  height: number;
  created_at: string;
  image_url: string;
  thumb_url: string;
};

type Page = { images: ImageSummary[]; next_before: string | null };

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await transport.fetch(path, init);
  if (!res.ok) {
    let detail = `The engine answered ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // not JSON
    }
    throw new HttpError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const listImages = (limit = 24, before?: string | null) =>
  json<Page>(
    `/products/${PRODUCT}/images?limit=${limit}${before ? `&before=${encodeURIComponent(before)}` : ""}`,
  );

/** Images whose words or meaning match `q`, best first (My creations search, ADR-0041). */
export async function searchImages(q: string): Promise<ImageSummary[]> {
  const found = await json<{ results: { id: string }[] }>(
    `/creations/search?q=${encodeURIComponent(q)}&kind=image&limit=24`,
  );
  const ids = found.results.map((r) => r.id);
  if (ids.length === 0) return [];
  const page = await json<Page>(`/products/${PRODUCT}/images?ids=${ids.join(",")}`);
  return page.images;
}

export const deleteImage = async (id: string) => {
  const res = await transport.fetch(`/products/${PRODUCT}/images/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404)
    throw new HttpError(res.status, "The image could not be deleted.");
};

/** "Today", "Yesterday" or a short date, for the recipe line. */
export function when(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const days = Math.floor((now.getTime() - d.getTime()) / 86_400_000);
  if (days <= 0 && d.getDate() === now.getDate()) return "Today";
  if (days <= 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function sizeName(width: number, height: number): string {
  const r = width / height;
  if (Math.abs(r - 1) < 0.02) return "Square 1:1";
  if (Math.abs(r - 4 / 3) < 0.03) return "Landscape 4:3";
  if (Math.abs(r - 3 / 4) < 0.03) return "Portrait 3:4";
  if (Math.abs(r - 16 / 9) < 0.03) return "Wide 16:9";
  if (Math.abs(r - 9 / 16) < 0.03) return "Tall 9:16";
  return `${width}×${height}`;
}
