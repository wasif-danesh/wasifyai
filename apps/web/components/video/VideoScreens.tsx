"use client";

import { STARTED_EVENT } from "@/hooks/use-video-activity";
import { putHandoff, takeHandoff } from "@/lib/handoff";
import { videoDownload, webTraining, webVideos } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import type { VideoMode, VideoSummary } from "@wasifyai/client";
import {
  ModelSelect,
  VideoLibrary,
  VideoWorkspace,
  useChoicesFor,
  useVideoLooks,
} from "@wasifyai/ui";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

/** What another screen hands over: a picture to animate ("Animate this"), a clip to carry on ("Extend this"). */
export const ANIMATE = "video-animate";
export const EXTEND = "video-extend";

type Start = { image: { url: string; name: string } | null; video: VideoSummary | null };

/** Make a video from words, animate a picture, or carry a video on (Extend): the shared make screen (also the
 * desktop's), talking to the BFF. A picture or a clip sent from another screen arrives through the tab's session
 * storage. */
export function VideoScreen({ mode }: { mode: Exclude<VideoMode, "import"> }) {
  const router = useRouter();
  const choices = useChoicesFor("video");
  const looks = useVideoLooks(webTraining); // what the person taught the video model, if anything
  // tell the header a clip is being made, so its badge shows up at once on every page
  const making = useCallback(() => window.dispatchEvent(new Event(STARTED_EVENT)), []);
  const [start, setStart] = useState<Start | null>(null);
  useEffect(() => {
    setStart({
      image: mode === "image" ? takeHandoff<{ url: string; name: string }>(ANIMATE) : null,
      video: mode === "extend" ? takeHandoff<VideoSummary>(EXTEND) : null,
    });
  }, [mode]);
  const extendThis = useCallback(
    (video: VideoSummary) => {
      putHandoff(EXTEND, video);
      router.push("/video/extend");
    },
    [router],
  );

  return (
    <div data-workspace className="h-[calc(100dvh-3rem)] min-h-[32rem]">
      {start ? (
        <VideoWorkspace
          key={`${mode}-${start.image?.url ?? ""}-${start.video?.id ?? ""}`}
          mode={mode}
          runs={webClient}
          videos={webVideos}
          header={
            choices ? (
              <ModelSelect group="video" api={choices} />
            ) : (
              <span className="font-medium">Video</span>
            )
          }
          downloadHref={(clip) => videoDownload({ videoId: clip.videoId })}
          hint="Takes a few minutes for 5 seconds and about twice as long for 8. You can explore the site while it's made."
          onMaking={making}
          looks={looks}
          onOpenLibrary={() => router.push("/video/library")}
          onExtendThis={extendThis}
          sourceImage={start.image}
          sourceVideo={start.video}
        />
      ) : null}
    </div>
  );
}

/** Your videos: every clip, including the ones being made, with search, download, delete and Extend this. */
export function VideoLibraryScreen() {
  const router = useRouter();
  return (
    <VideoLibrary
      videos={webVideos}
      className="max-w-none px-0 pt-0 pb-0"
      subtitle="Every clip you made."
      downloadHref={(v) => videoDownload({ id: v.id })}
      onCreate={() => router.push("/video")}
      onExtend={(video) => {
        putHandoff(EXTEND, video);
        router.push("/video/extend");
      }}
    />
  );
}
