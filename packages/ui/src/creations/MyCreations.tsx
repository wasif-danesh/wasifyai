"use client";

import type { CreationsApi, Recent } from "@wasifyai/client";
import { useEffect, useState } from "react";
import { Notice } from "../components/notice";
import { CreationsList } from "./CreationsList";
import type { CreationsNav, Filter } from "./model";

/**
 * My creations (ADR-0040): everything a person made, in one place, with search by meaning and a filter for each kind. The same screen
 * on the web (Library) and in the app window; each app says where an entry opens.
 */
export function MyCreations({
  api,
  nav,
  initialFilter = "all",
  className,
}: {
  api: CreationsApi;
  nav: CreationsNav;
  initialFilter?: Filter;
  className?: string;
}) {
  const [recent, setRecent] = useState<Recent | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let gone = false;
    api
      .recent()
      .then((r) => !gone && setRecent(r))
      .catch(() => !gone && setFailed(true));
    return () => {
      gone = true;
    };
  }, [api]);

  const nothing =
    recent !== null &&
    !recent.images &&
    !recent.videos &&
    !recent.songs.length &&
    !recent.speeches.length &&
    !recent.transcripts.length &&
    !recent.lipsyncs.length;

  return (
    <div className={className ?? "mx-auto grid w-full max-w-5xl gap-5 p-[clamp(1rem,3vw,2rem)]"}>
      <header className="grid gap-1.5">
        <h1 className="font-semibold text-step-2">My creations</h1>
        <p className="max-w-[34rem] text-muted-foreground">
          Your music, images, videos, speech, transcripts and lip syncs, all together. Pick up where
          inspiration left off.
        </p>
      </header>
      {failed || nothing ? (
        <Notice tone="error" title="Couldn't load your creations">
          The service isn't answering right now. Try again in a moment.
        </Notice>
      ) : recent === null ? (
        <output className="text-muted-foreground">Looking for your creations…</output>
      ) : (
        <>
          {recent.failed.includes("images") ? (
            <Notice tone="error" title="Couldn't load your images">
              Your other creations are still available below.
            </Notice>
          ) : null}
          {recent.failed.includes("videos") ? (
            <Notice tone="error" title="Couldn't load your videos">
              Your other creations are still available below.
            </Notice>
          ) : null}
          {recent.failed.includes("voice") ? (
            <Notice tone="error" title="Couldn't load your music, speech or lip syncs">
              Your other creations are still available below.
            </Notice>
          ) : null}
          <CreationsList
            api={api}
            nav={nav}
            songs={recent.songs}
            images={recent.images}
            videos={recent.videos}
            speeches={recent.speeches}
            transcripts={recent.transcripts}
            lipsyncs={recent.lipsyncs}
            initialFilter={initialFilter}
          />
        </>
      )}
    </div>
  );
}
