"use client";

import { webAssistant, webImages, webVideoBuilder, webVideos } from "@/lib/library";
import { videoDownload } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import { ModelSelect, VideoBuilder, useChoicesFor } from "@wasifyai/ui";
import { useRouter } from "next/navigation";

/** Motion graphics: the shared screen (also the desktop's), talking to the BFF. The drawing is done on the service's worker. */
export function VideoBuilderScreen() {
  const router = useRouter();
  const choices = useChoicesFor("chat");
  return (
    <VideoBuilder
      api={webVideoBuilder}
      videos={webVideos}
      place="service"
      downloadHref={(id) => videoDownload({ id })}
      onOpenLibrary={() => router.push("/video/library")}
      assistant={{
        runs: webClient,
        api: webAssistant,
        images: webImages,
        model: choices ? <ModelSelect group="chat" api={choices} /> : undefined,
      }}
    />
  );
}
