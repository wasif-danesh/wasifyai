"use client";

import { Notice } from "@/components/Notice";
import { DeleteControls } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { clock, fullDate } from "@/lib/format";
import { actions, eyebrow, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { LipSyncSummary } from "@wasifyai/contracts";
import { useEffect, useState } from "react";

const POLL_MS = 10_000;

/** One lip sync: the player and a download, or "being made" (it checks again until it is ready), or why
 * it failed. Deleting asks twice. */
export function LipSyncView({ initial }: { initial: LipSyncSummary }) {
  const [item, setItem] = useState(initial);

  useEffect(() => {
    if (item.status !== "working") return;
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/products/wasifyai-lipsync/lipsyncs/${item.id}`);
        if (res.ok) setItem((await res.json()) as LipSyncSummary);
      } catch {
        // try again at the next tick
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [item.id, item.status]);

  return (
    <article className={cn(panel, "@container")}>
      {item.status === "done" && item.video_url ? (
        <figure className="m-0 grid justify-items-center">
          {/* biome-ignore lint/a11y/useMediaCaption: the clip carries its own voice */}
          <video
            className="h-auto max-h-[70vh] max-w-full rounded-xl bg-black shadow-card"
            controls
            playsInline
            preload="metadata"
            poster={item.poster_url ?? undefined}
            src={item.video_url}
          />
        </figure>
      ) : item.status === "working" ? (
        <Notice tone="info" title="Your lip sync is being created">
          This can take a while. You can leave this page: it will be here when it's ready, and we'll
          tell you.
        </Notice>
      ) : (
        <Notice tone="error" title="This lip sync couldn't be made">
          {item.error ?? "Please try again."}
        </Notice>
      )}
      <div className="grid gap-[0.9rem]">
        <span className={eyebrow}>
          {item.source === "audio" ? "From a voice" : "From a script"} · {clock(item.seconds)} ·{" "}
          {fullDate(item.created_at)}
        </span>
        {item.text ? <p>{item.text}</p> : null}
        {item.style ? <p className="text-muted-foreground">{item.style}</p> : null}
        <div className={actions}>
          {item.status === "done" ? (
            <Button asChild>
              <a href={`/api/products/wasifyai-lipsync/lipsyncs/${item.id}/download`} download>
                Download
              </a>
            </Button>
          ) : null}
          {item.status === "working" ? null : (
            <DeleteControls
              url={`/api/products/wasifyai-lipsync/lipsyncs/${item.id}`}
              noun="lip sync"
              label={item.status === "failed" ? "Remove" : "Delete"}
            />
          )}
        </div>
      </div>
    </article>
  );
}
