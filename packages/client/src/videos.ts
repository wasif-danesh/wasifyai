import { HttpError, type Transport, errorMessage } from "./transport";
// A person's finished videos, from the product's read routes (`/products/wasifyai-video/videos`):
// list, search, open, save a copy, delete. The same routes serve the web app and the desktop window;
// only the transport differs.
import type { VideoMode } from "./video-flow";

export const VIDEO_PRODUCT_ID = "wasifyai-video";

export type VideoStatus = "working" | "done" | "failed";

export type VideoSummary = {
  id: string;
  prompt: string;
  mode: VideoMode;
  status: VideoStatus;
  seconds: number;
  created_at: string;
  width: number | null;
  height: number | null;
  /** plain text for the person, only when the clip failed */
  error: string | null;
  /** only when the clip is done */
  video_url: string | null;
  poster_url: string | null;
  /** what it was made from: the clip it carries on (mode "extend") or the picture it animates (mode "image"),
   * or null (ADR-0093, U8) */
  source_id?: string | null;
};

export type VideoPage = { videos: VideoSummary[]; next_before: string | null };

export type VideoListOptions = {
  limit?: number;
  before?: string | null;
  status?: VideoStatus;
  /** only the clips made from this clip or picture */
  source?: string;
};

export type VideosApi = {
  list(options?: VideoListOptions): Promise<VideoPage>;
  /** Videos whose words or meaning match `q`, best first (My creations search, ADR-0041). */
  search(q: string): Promise<VideoSummary[]>;
  get(id: string): Promise<VideoSummary>;
  remove(id: string): Promise<void>;
  /** Save a copy into the person's folder; only the desktop engine offers it. */
  exportCopy(id: string, path?: string): Promise<{ name: string; path: string }>;
  /**
   * Add a video file from the person's computer to their videos. The engine makes it fit the model (size,
   * 24 frames a second, up to 30 seconds, no sound) and answers with the new video.
   */
  importVideo(file: File): Promise<VideoSummary>;
};

export function createVideosApi(transport: Transport, product = VIDEO_PRODUCT_ID): VideosApi {
  const base = `/products/${product}/videos`;

  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }

  return {
    list({ limit = 24, before, status, source } = {}) {
      const q = new URLSearchParams({ limit: String(limit) });
      if (before) q.set("before", before);
      if (status) q.set("status", status);
      if (source) q.set("source", source);
      return json<VideoPage>(`${base}?${q}`);
    },

    async search(q) {
      const found = await json<{ results: { id: string }[] }>(
        `/creations/search?${new URLSearchParams({ q, kind: "video", limit: "24" })}`,
      );
      const ids = found.results.map((r) => r.id);
      if (ids.length === 0) return [];
      const page = await json<VideoPage>(`${base}?ids=${ids.join(",")}`);
      return page.videos;
    },

    get: (id) => json<VideoSummary>(`${base}/${encodeURIComponent(id)}`),

    async remove(id) {
      const res = await transport.fetch(`${base}/${encodeURIComponent(id)}`, { method: "DELETE" });
      // gone already is as good as deleted
      if (!res.ok && res.status !== 404) {
        throw new HttpError(res.status, await errorMessage(res));
      }
    },

    exportCopy: (id, path) =>
      json<{ name: string; path: string }>(`${base}/${encodeURIComponent(id)}/export`, {
        method: "POST",
        ...(path
          ? { headers: { "content-type": "application/json" }, body: JSON.stringify({ path }) }
          : {}),
      }),

    importVideo(file) {
      const form = new FormData();
      form.append("file", file);
      return json<VideoSummary>(`${base}/import`, { method: "POST", body: form });
    },
  };
}

/** The clip's length for a card: "5 s". */
export function clipLength(seconds: number): string {
  return `${seconds} s`;
}
