"use client";

import { Notice } from "@/components/Notice";
import { DeleteControls } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { fullDate } from "@/lib/format";
import { actions, eyebrow, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { VideoSummary } from "@wasifyai/contracts";
import { useEffect, useState } from "react";

const POLL_MS = 10_000;

/** One clip: the player and a download, or "being made" (it checks again until it is ready), or why it
 * failed. Deleting asks twice. */
export function VideoView({ initial }: { initial: VideoSummary }) {
  const [video, setVideo] = useState(initial);

  useEffect(() => {
    if (video.status !== "working") return;
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/products/wasifyai-video/videos/${video.id}`);
        if (res.ok) setVideo((await res.json()) as VideoSummary);
      } catch {
        // try again at the next tick
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [video.id, video.status]);

  const when = fullDate(video.created_at);
  return (
    <article className={cn(panel, "@container")}>
      {video.status === "done" && video.video_url ? (
        <figure className="m-0 grid justify-items-center">
          {/* biome-ignore lint/a11y/useMediaCaption: generated clips have no speech to caption */}
          <video
            className="h-auto max-h-[70vh] max-w-full rounded-xl bg-black shadow-card"
            controls
            playsInline
            preload="metadata"
            poster={video.poster_url ?? undefined}
            src={video.video_url}
          />
        </figure>
      ) : video.status === "working" ? (
        <Notice tone="info" title="Your video is being created">
          This takes a few minutes. You can leave this page: it will be here when it's ready, and
          we'll tell you.
        </Notice>
      ) : (
        <Notice tone="error" title="This video couldn't be made">
          {video.error ?? "Please try again."}
        </Notice>
      )}
      <div className="grid gap-[0.9rem]">
        <span className={eyebrow}>
          {video.mode === "image" ? "From a picture" : "From text"} · {video.seconds} seconds ·{" "}
          {when}
        </span>
        <p>{video.prompt}</p>
        <div className={actions}>
          {video.status === "done" ? (
            <Button asChild>
              <a href={`/api/products/wasifyai-video/videos/${video.id}/download`} download>
                Download
              </a>
            </Button>
          ) : null}
          {video.status === "working" ? null : (
            <DeleteControls
              url={`/api/products/wasifyai-video/videos/${video.id}`}
              noun="video"
              label={video.status === "failed" ? "Remove" : "Delete"}
            />
          )}
        </div>
      </div>
    </article>
  );
}
