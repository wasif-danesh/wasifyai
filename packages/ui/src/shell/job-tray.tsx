"use client";

import { Popover as PopoverPrimitive } from "radix-ui";
import { useEffect, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Spinner } from "../components/spinner";

/** One running job, in words: what is being made, since when, who asked, and how to stop it. */
export type TrayJob = {
  id: string;
  /** what is happening ("Making a picture") */
  label: string;
  /** who started it when it was not this person here ("Codex") */
  from?: string | null;
  seconds?: number;
  onStop?: () => Promise<void> | void;
};

export const TRAY_POLL_MS = 4_000;

/** What a running action is doing, in words (`docs/contracts/actions.json` ids). */
const ACTION_WORDS: Record<string, string> = {
  "image.generate": "Making a picture",
  "image.edit": "Changing a picture",
  "image.inpaint": "Painting over part of a picture",
  "image.reference": "Making a picture from a reference",
  "video.generate": "Making a video",
  "video.animate": "Animating a picture",
  "video.extend": "Extending a video",
  "motion.make": "Making motion graphics",
  "motion.revise": "Changing motion graphics",
  "video_builder.render": "Rendering a video",
  "speech.speak": "Making speech",
  "speech.transcribe": "Transcribing a recording",
  "voice.clone": "Cloning a voice",
  "voice.design": "Making a voice",
  "voice.convert": "Changing a voice",
  "voice.edit_speech": "Editing speech",
  "dub.make": "Dubbing a recording",
  "dub.script": "Writing a dub script",
  "audiobook.make": "Reading an audiobook",
  "audiobook.plan": "Finding the chapters",
  "lipsync.make": "Making a lip sync video",
  "music.generate": "Making a song",
  "music.lyrics": "Writing lyrics",
  "music.separate": "Splitting a song",
  "model3d.generate": "Making a 3D model",
  "music.analyse": "Finding the beats of a song",
  "creative.plan": "Planning a music video",
  "models.download": "Getting a model",
  "train.start": "Teaching a model",
  "notebook.ask": "Answering from a notebook",
  "notebook.studio_output": "Making a notebook output",
  "notebook.add_source": "Reading a source",
  "web.search": "Searching the web",
  "web.read": "Reading a page",
  "external.call": "Using another app's tool",
};

/** "Making a picture" for `image.generate`; an id the map does not know is said as plain words. */
export function jobLabel(actionId: string): string {
  const known = ACTION_WORDS[actionId];
  if (known) return known;
  const words = actionId.replace(/[._]/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function since(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} min ${Math.round(seconds % 60)} s`;
}

/**
 * The running jobs, in the top bar of both apps (ADR-0093 decision 6): a quiet button with a count while
 * something runs, and a list with Stop. The app says how it lists its jobs; the tray asks every few seconds
 * while the page is visible.
 */
export function JobTray({
  load,
  pollMs = TRAY_POLL_MS,
}: { load: () => Promise<TrayJob[]>; pollMs?: number }) {
  const [jobs, setJobs] = useState<TrayJob[]>([]);
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let gone = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      if (gone) return;
      if (!document.hidden) {
        try {
          const next = await load();
          if (!gone) setJobs(next);
        } catch {
          // the app cannot list jobs right now: the tray just stays as it was
        }
      }
      timer = setTimeout(tick, pollMs);
    };
    void tick();
    const onVisible = () => {
      if (!document.hidden) void tick();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      gone = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load, pollMs]);
  const count = jobs.length;
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <button
          type="button"
          aria-label={count === 0 ? "Nothing running" : `${count} running`}
          title={count === 0 ? "Nothing running" : `${count} running`}
          data-count={count}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-md border px-2 text-sm outline-none transition-colors hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50",
            count === 0 ? "text-muted-foreground" : "border-primary/40 bg-accent text-foreground",
          )}
        >
          {count > 0 ? (
            <Spinner className="size-3.5" />
          ) : (
            <span aria-hidden="true" className="size-2 rounded-full bg-muted-foreground/40" />
          )}
          <span className="tabular-nums">{count > 0 ? count : ""}</span>
          <span className="max-sm:sr-only">
            {count === 1 ? "running" : count > 1 ? "running" : "Idle"}
          </span>
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="end"
          sideOffset={6}
          className="z-50 w-[min(22rem,calc(100vw-2rem))] rounded-md border bg-popover p-2 text-popover-foreground shadow-card"
        >
          <h3 className="m-0 px-2 py-1 font-semibold text-sm">Running now</h3>
          {count === 0 ? (
            <p className="m-0 px-2 py-2 text-muted-foreground text-sm">Nothing is running.</p>
          ) : (
            <ul className="m-0 grid list-none gap-1 p-0">
              {jobs.map((j) => (
                <li key={j.id} className="flex items-center gap-3 rounded-md px-2 py-1.5">
                  <Spinner className="size-3.5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{j.label}</div>
                    <div className="text-muted-foreground text-xs">
                      {j.seconds !== undefined ? since(j.seconds) : null}
                      {j.from ? ` · from ${j.from}` : ""}
                    </div>
                  </div>
                  {j.onStop ? (
                    <Button
                      type="button"
                      size="xs"
                      variant="outline"
                      aria-label={`Stop ${j.label}`}
                      onClick={() => {
                        setProblem(null);
                        Promise.resolve(j.onStop?.()).catch(() =>
                          setProblem("That could not be stopped."),
                        );
                      }}
                    >
                      Stop
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          {problem ? <p className="m-0 px-2 py-1 text-destructive text-xs">{problem}</p> : null}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
