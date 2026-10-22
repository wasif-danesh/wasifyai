"use client";

import { webVideoBuilder, webVideos } from "@/lib/library";
import { videoDownload } from "@/lib/library";
import { VideoBuilder } from "@wasifyai/ui";
import { useRouter } from "next/navigation";

/** Video Builder: the shared screen (also the desktop's), talking to the BFF. The drawing is done on the service's worker. */
export function VideoBuilderScreen() {
  const router = useRouter();
  return (
    <VideoBuilder
      api={webVideoBuilder}
      videos={webVideos}
      place="service"
      downloadHref={(id) => videoDownload({ id })}
      onOpenLibrary={() => router.push("/video/library")}
    />
  );
}
