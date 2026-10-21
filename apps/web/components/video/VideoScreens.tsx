"use client";

import { STARTED_EVENT } from "@/hooks/use-video-activity";
import { videoDownload, webVideos } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import { VideoLibrary, VideoWorkspace } from "@wasifyai/ui";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

/** Make a video from words, or animate a picture: the shared screen (also the desktop's), talking to the BFF. */
export function VideoScreen({ mode }: { mode: "text" | "image" }) {
  const router = useRouter();
  // tell the header a clip is being made, so its badge shows up at once on every page
  const making = useCallback(() => window.dispatchEvent(new Event(STARTED_EVENT)), []);
  return (
    <div className="grid gap-6">
      <header className="mx-auto grid w-full max-w-3xl gap-1">
        <h1 className="font-semibold text-2xl">
          {mode === "text" ? "Make a video" : "Animate a picture"}
        </h1>
        <p className="text-muted-foreground">
          {mode === "text"
            ? "Describe a scene and get a short clip."
            : "Choose a picture and say what should move."}
        </p>
      </header>
      <VideoWorkspace
        mode={mode}
        runs={webClient}
        videos={webVideos}
        downloadHref={(r) => videoDownload({ videoId: r.videoId })}
        hint="Takes a few minutes for 5 seconds and about twice as long for 8. You can explore the site while it's made."
        onMaking={making}
        onOpenLibrary={() => router.push("/video/library")}
      />
    </div>
  );
}

/** Your videos: every clip, including the ones being made, with search, download and delete. */
export function VideoLibraryScreen() {
  const router = useRouter();
  return (
    <VideoLibrary
      videos={webVideos}
      className="max-w-none px-0 pt-0 pb-0"
      subtitle="Every clip you made."
      downloadHref={(v) => videoDownload({ id: v.id })}
      onCreate={() => router.push("/video")}
    />
  );
}
