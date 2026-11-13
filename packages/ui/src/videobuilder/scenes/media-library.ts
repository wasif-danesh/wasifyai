// The Library as the editor's Add tools see it: the same on the desktop and the web, with each app saying
// where a file can be read from.
import type { ImagesApi, VideosApi } from "@wasifyai/client";
import type { LibraryItem, MediaLibrary } from "./MediaTools";

const EXT: Record<LibraryItem["kind"], string> = { image: "png", video: "mp4", audio: "wav" };

export function mediaLibrary({
  images,
  videos,
  hrefOf,
}: {
  images?: Pick<ImagesApi, "list">;
  videos?: Pick<VideosApi, "list">;
  /** where a file of the Library can be fetched from here */
  hrefOf: (item: LibraryItem) => string | Promise<string>;
}): MediaLibrary {
  const urls = new Map<string, string>();
  return {
    async list() {
      const [pictures, clips] = await Promise.all([
        images?.list({ limit: 40 }),
        videos?.list({ limit: 40, status: "done" }),
      ]);
      const out: LibraryItem[] = [];
      for (const p of pictures?.images ?? []) {
        urls.set(`image:${p.id}`, p.image_url);
        out.push({ kind: "image", id: p.id, title: p.prompt });
      }
      for (const v of clips?.videos ?? []) {
        if (v.video_url) urls.set(`video:${v.id}`, v.video_url);
        out.push({ kind: "video", id: v.id, title: v.prompt });
      }
      return out;
    },
    async read(item) {
      const res = await fetch(await hrefOf(item));
      if (!res.ok) throw new Error("That could not be read from your Library.");
      const name = `${item.title.slice(0, 60) || "From the Library"}.${EXT[item.kind]}`;
      return new File([await res.blob()], name);
    },
  };
}
