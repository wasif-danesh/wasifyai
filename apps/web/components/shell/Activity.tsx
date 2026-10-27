"use client";

import { Button } from "@/components/ui/button";
import { useVideoActivity } from "@/hooks/use-video-activity";
import { clamp2 } from "@/lib/styles";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";

type Notice = { id: string; status: "done" | "failed"; prompt: string; error?: string };

const WORDS = {
  working: "Making your video…",
  ready: "Your video is ready",
  failed: "Your video couldn't be made",
  open: (id: string) => `/video/creations/${id}`,
  again: "/video",
  verb: "Watch it",
};

/**
 * The notice when something being made finishes or fails (ADR-0037). What is being made shows in the bar's job
 * tray (stage U2); `activity` is the shell's own poll, so the page asks once.
 */
export function Activity({
  enabled = true,
  activity,
}: {
  enabled?: boolean;
  activity?: ReturnType<typeof useVideoActivity>;
}) {
  // The notice is fixed to the window, but the top bar's blur makes it the containing block of
  // everything fixed inside it: the notice must be put on the page itself to stay in view.
  const [page, setPage] = useState<HTMLElement | null>(null);
  useEffect(() => setPage(document.body), []);
  const onPage = (node: ReactNode) => (page ? createPortal(node, page) : null);
  const polled = useVideoActivity(enabled && !activity);
  const video = activity ?? polled;
  const shown: { notice: Notice; dismiss: () => void } | null = video.notice
    ? { notice: video.notice, dismiss: video.dismiss }
    : null;
  return (
    <>
      {onPage(
        <div
          className="pointer-events-none fixed inset-x-0 bottom-4 z-50 grid justify-items-end px-4"
          aria-live="polite"
        >
          {shown ? (
            <div
              data-tone={shown.notice.status === "done" ? "ok" : "error"}
              className={cn(
                "pointer-events-auto grid max-w-[min(26rem,100%)] gap-[0.4rem] rounded-lg border bg-surface px-4 py-[0.9rem] shadow-card",
                shown.notice.status !== "done" && "border-destructive",
              )}
            >
              <strong>{shown.notice.status === "done" ? WORDS.ready : WORDS.failed}</strong>
              <span className="block text-step--1 text-muted-foreground">
                <span className={clamp2}>
                  {shown.notice.status === "done"
                    ? shown.notice.prompt
                    : (shown.notice.error ?? "Please try again.")}
                </span>
              </span>
              <span className="flex flex-wrap gap-2">
                {shown.notice.status === "done" ? (
                  <Button asChild size="sm">
                    <Link href={WORDS.open(shown.notice.id)} onClick={shown.dismiss}>
                      {WORDS.verb}
                    </Link>
                  </Button>
                ) : (
                  <Button asChild size="sm" variant="outline">
                    <Link href={WORDS.again} onClick={shown.dismiss}>
                      Try again
                    </Link>
                  </Button>
                )}
                <Button type="button" size="sm" variant="outline" onClick={shown.dismiss}>
                  Dismiss
                </Button>
              </span>
            </div>
          ) : null}
        </div>,
      )}
    </>
  );
}
