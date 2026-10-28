"use client";

import type { CreationsApi, Recent } from "@wasifyai/client";
import { Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { Spinner } from "../components/spinner";
import { CreationsList } from "./CreationsList";
import type { CreationsNav, Filter } from "./model";

/**
 * The Library (ADR-0040, ADR-0093 U8): everything a person made, in one place, with search by meaning, a filter
 * and a count for each kind, sorting, choosing several to save or delete, and a detail view for each. The same
 * screen on the web and in the app window; each app says where an entry opens and which tools it can be handed to.
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
  const [round, setRound] = useState(0); // read again after a recording is added
  const [adding, setAdding] = useState(false);
  const [addProblem, setAddProblem] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: `round` asks for a new read
  useEffect(() => {
    let gone = false;
    api
      .recent()
      .then((r) => !gone && setRecent(r))
      .catch(() => !gone && setFailed(true));
    return () => {
      gone = true;
    };
  }, [api, round]);

  const add = useCallback(
    async (file: File) => {
      setAdding(true);
      setAddProblem(null);
      try {
        await api.addRecording(file);
        setRound((n) => n + 1);
      } catch (e) {
        setAddProblem(e instanceof Error ? e.message : "That recording could not be added.");
      } finally {
        setAdding(false);
      }
    },
    [api],
  );

  const nothing =
    recent !== null &&
    !recent.images &&
    !recent.videos &&
    !recent.songs.length &&
    !recent.speeches.length &&
    !recent.transcripts.length &&
    !recent.lipsyncs.length &&
    !recent.others?.models3d.length &&
    !recent.others?.compositions.length &&
    !recent.others?.notebooks.length &&
    !recent.others?.taught.length;

  return (
    <div className={className ?? "mx-auto grid w-full max-w-5xl gap-5 p-[clamp(1rem,3vw,2rem)]"}>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1.5">
          <h1 className="font-semibold text-step-2">Library</h1>
          <p className="max-w-[34rem] text-muted-foreground">
            Everything you made, in one place: pictures, videos, music, speech and the rest. Open
            one to see what made it and what to do with it.
          </p>
        </div>
        <input
          ref={picker}
          type="file"
          accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.caf,.aiff"
          className="sr-only"
          tabIndex={-1}
          aria-label="Add a recording from this computer"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) void add(f);
          }}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={adding}
          onClick={() => picker.current?.click()}
        >
          {adding ? <Spinner /> : <Upload aria-hidden="true" />} Add a recording
        </Button>
      </header>
      {addProblem ? (
        <Notice tone="error" title="That recording could not be added">
          {addProblem}
        </Notice>
      ) : null}
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
            key={round}
            api={api}
            nav={nav}
            songs={recent.songs}
            images={recent.images}
            videos={recent.videos}
            speeches={recent.speeches}
            transcripts={recent.transcripts}
            lipsyncs={recent.lipsyncs}
            others={recent.others}
            initialFilter={initialFilter}
          />
        </>
      )}
    </div>
  );
}
