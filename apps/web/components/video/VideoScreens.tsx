"use client";

import { STARTED_EVENT } from "@/hooks/use-video-activity";
import { videoDownload, webVideos } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import type { VideoMode } from "@wasifyai/client";
import {
  ModelSelect,
  PageHeader,
  TopBarSlot,
  VideoLibrary,
  VideoWorkspace,
  useChoicesFor,
} from "@wasifyai/ui";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

const TITLES: Record<Exclude<VideoMode, "import">, [string, string]> = {
  text: ["Make a video", "Describe a scene and get a short clip."],
  image: ["Animate a picture", "Choose a picture and say what should move."],
  extend: [
    "Extend a video",
    "Choose one of your videos, or add one from your computer, and carry it on for five or eight more seconds.",
  ],
};

/** Make a video from words, animate a picture, or carry a video on (Extend): the shared screen (also the desktop's), talking to the BFF. */
export function VideoScreen({ mode }: { mode: Exclude<VideoMode, "import"> }) {
  const router = useRouter();
  const choices = useChoicesFor("video");
  // tell the header a clip is being made, so its badge shows up at once on every page
  const making = useCallback(() => window.dispatchEvent(new Event(STARTED_EVENT)), []);
  return (
    <TopBarSlot>
      {choices ? (
        <PageHeader className="flex h-14 shrink-0 items-center gap-4 border-b px-6 pt-1">
          <div className="flex items-center gap-2 ps-2 text-sm">
            <ModelSelect group="video" api={choices} />
          </div>
        </PageHeader>
      ) : null}
      <div className="grid gap-6">
        <header className="mx-auto grid w-full max-w-3xl gap-1">
          <h1 className="font-semibold text-2xl">{TITLES[mode][0]}</h1>
          <p className="text-muted-foreground">{TITLES[mode][1]}</p>
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
    </TopBarSlot>
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
