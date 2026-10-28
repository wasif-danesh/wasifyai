"use client";

import { useAui } from "@assistant-ui/react";
import type { CreationsApi } from "@wasifyai/client";
import {
  AudioLines,
  BookOpen,
  Box,
  Film,
  GraduationCap,
  ImageIcon,
  type LucideIcon,
  Music,
  Shapes,
} from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "../cn";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Spinner } from "../components/spinner";
import { type Entry, latestEntries, toRow } from "../creations/model";
import { useChoicesFor } from "../models/context";
import type { GroupId } from "../models/types";
import { TRAY_POLL_MS, type TrayJob } from "../shell/job-tray";

/** What a quick start opens (the app knows where each one is). */
export type QuickStartId =
  | "picture"
  | "video"
  | "speech"
  | "song"
  | "notebook"
  | "model3d"
  | "motion"
  | "train";

const STARTS: { id: QuickStartId; title: string; line: string; Icon: LucideIcon; group?: GroupId }[] = [
  { id: "picture", title: "Picture", line: "Describe it, get a picture", Icon: ImageIcon, group: "images" },
  { id: "video", title: "Video", line: "A short clip from words or a picture", Icon: Film, group: "video" },
  { id: "speech", title: "Speech", line: "Type it and hear it", Icon: AudioLines, group: "voice" },
  { id: "song", title: "Song", line: "Songs, instrumentals and sounds", Icon: Music, group: "music" },
  { id: "notebook", title: "Notebook", line: "Ask your own documents", Icon: BookOpen },
  { id: "model3d", title: "3D model", line: "A 3D model from a picture", Icon: Box, group: "three_d" },
  { id: "motion", title: "Motion graphics", line: "Animated titles and charts", Icon: Shapes },
  { id: "train", title: "Train models", line: "Teach it a style, a look or a voice", Icon: GraduationCap },
]; // biome-ignore format: a table

/** Whether the model a quick start needs is ready, in a few words; nothing where the app does not say. */
function Readiness({ group }: { group: GroupId }) {
  const api = useChoicesFor(group);
  const [state, setState] = useState<"ready" | "download" | "choose" | null>(null);
  useEffect(() => {
    if (!api) return;
    let gone = false;
    api
      .list()
      .then((list) => {
        if (gone) return;
        const chosen = list.choices.find((c) => c.chosen);
        setState(!chosen ? "choose" : chosen.state === "ready" ? "ready" : "download");
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [api]);
  if (!state) return null;
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          state === "ready" ? "bg-ok" : state === "download" ? "bg-warn" : "bg-muted-foreground/50",
        )}
      />
      {state === "ready" ? "Ready" : state === "download" ? "Needs a download" : "Choose a model"}
    </span>
  );
}

/** The products, one small card each: one line, whether its model is ready, and the box's words carried over. */
function QuickStarts({
  offered,
  onStart,
}: {
  offered?: QuickStartId[];
  onStart: (id: QuickStartId, text: string) => void;
}) {
  const aui = useAui();
  const shown = STARTS.filter((s) => !offered || offered.includes(s.id));
  return (
    <nav aria-label="Quick starts">
      <ul className="m-0 grid list-none grid-cols-2 gap-2 p-0 sm:grid-cols-4">
        {shown.map(({ id, title, line, Icon, group }) => (
          <li key={id}>
            <button
              type="button"
              onClick={() => {
                let text = "";
                try {
                  text = aui.composer().getState().text;
                } catch {
                  // no box: the tool opens empty
                }
                onStart(id, text.trim());
              }}
              className="grid h-full w-full gap-1 rounded-lg border bg-surface p-3 text-start outline-none transition-colors hover:border-primary/45 hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex items-center gap-2 font-medium text-sm">
                <Icon className="size-4 text-primary" aria-hidden="true" />
                {title}
              </span>
              <span className="text-muted-foreground text-xs">{line}</span>
              {group ? <Readiness group={group} /> : null}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function since(seconds?: number): string {
  if (seconds === undefined) return "";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  return `${Math.floor(seconds / 60)} min`;
}

/** What runs now, read every few seconds while the page is visible; nothing when nothing runs. */
function RunningNow({ load }: { load: () => Promise<TrayJob[]> }) {
  const [jobs, setJobs] = useState<TrayJob[]>([]);
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
          // the next tick tries again
        }
      }
      if (!gone) timer = setTimeout(tick, TRAY_POLL_MS);
    };
    void tick();
    return () => {
      gone = true;
      if (timer) clearTimeout(timer);
    };
  }, [load]);
  if (jobs.length === 0) return null;
  return (
    <section aria-label="Running now" className="grid min-w-0 gap-1.5">
      <h2 className="m-0 font-semibold text-sm">Running now</h2>
      {/* one column that may shrink: a long job's name is cut, not the page widened */}
      <ul className="m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-1 p-0">
        {jobs.map((j) => (
          <li key={j.id} className="flex items-center gap-2 text-sm">
            <Spinner />
            <span className="min-w-0 flex-1 truncate">{j.label}</span>
            {j.seconds !== undefined ? (
              <span className="text-muted-foreground text-xs tabular-nums">{since(j.seconds)}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

const COVER: Partial<Record<Entry["kind"], (e: Entry) => string | null>> = {
  image: (e) => (e.kind === "image" ? e.image.thumb_url : null),
  video: (e) => (e.kind === "video" ? e.video.poster_url : null),
  lipsync: (e) => (e.kind === "lipsync" ? e.lipsync.poster_url : null),
};

/** The last six things made, from the one Library, each opening there. */
function RecentCreations({
  api,
  onOpen,
  onSeeAll,
}: {
  api: CreationsApi;
  onOpen: (entry: Entry) => void;
  onSeeAll?: () => void;
}) {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  useEffect(() => {
    let gone = false;
    api
      .recent()
      .then((r) => !gone && setEntries(latestEntries(r, 6)))
      .catch(() => !gone && setEntries([]));
    return () => {
      gone = true;
    };
  }, [api]);
  if (entries !== null && entries.length === 0) return null;
  const items: RecentItem[] = (entries ?? []).map((e) => {
    const row = toRow(e);
    const cover = COVER[e.kind]?.(e) ?? null;
    return {
      id: `${e.kind}:${e.id}`,
      cover: cover ? (
        <img src={cover} alt="" className="size-full object-cover" />
      ) : (
        <span className="grid size-full place-items-center bg-muted p-1 text-center text-xs leading-tight">
          {row.kindLabel}
        </span>
      ),
      label: `Open: ${row.title}`,
      onOpen: () => onOpen(e),
    };
  });
  return (
    <RecentStrip title="Recent" items={items} loading={entries === null} onSeeAll={onSeeAll} />
  );
}

/** Under the chat box of the home (ADR-0093, stage U9): the quick starts, what runs now, and what was made last. */
export function HomeStart({
  offered,
  onStart,
  running,
  creations,
  onOpenEntry,
  onOpenLibrary,
}: {
  offered?: QuickStartId[];
  onStart?: (id: QuickStartId, text: string) => void;
  running?: () => Promise<TrayJob[]>;
  creations?: CreationsApi;
  onOpenEntry?: (entry: Entry) => void;
  onOpenLibrary?: () => void;
}) {
  return (
    <div
      className="mx-auto grid w-full max-w-3xl grid-cols-[minmax(0,1fr)] gap-6"
      data-slot="home-start"
    >
      {onStart ? <QuickStarts offered={offered} onStart={onStart} /> : null}
      {running ? <RunningNow load={running} /> : null}
      {creations && onOpenEntry ? (
        <RecentCreations api={creations} onOpen={onOpenEntry} onSeeAll={onOpenLibrary} />
      ) : null}
    </div>
  );
}
