import type { LipSyncCard as LipSyncEntry, VideoSummary } from "@wasifyai/client";
import {
  AudioLines,
  BookOpen,
  Box,
  Clapperboard,
  GraduationCap,
  type LucideIcon,
  Mic,
  Shapes,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../cn";
import { Badge } from "../components/badge";
import { Spinner } from "../components/spinner";
import { clamp2, coverTile } from "../styles";
import { clock } from "../voice/format";
import { NavLink } from "./NavLink";
import { styleTags, timeAgo } from "./format";
import { type CreationsNav, type Entry, KIND_LABEL, toRow } from "./model";

/** One card in My creations: a cover, what kind it is, a title, a few tags and when it was made. */
function Card({
  nav,
  to,
  kind,
  cover,
  title,
  tags,
  when,
  lang,
  status,
  onOpen,
}: {
  nav: CreationsNav;
  to: Entry;
  /** open the entry here (the Library's detail view) instead of going to its tool */
  onOpen?: (entry: Entry) => void;
  kind: string;
  cover: ReactNode;
  title: string;
  tags?: ReactNode;
  when: string;
  lang?: string;
  status?: string;
}) {
  return (
    <NavLink
      nav={nav}
      to={to}
      onClick={
        onOpen
          ? (e) => {
              if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return; // a new tab: the tool
              e.preventDefault();
              onOpen(to);
            }
          : undefined
      }
      data-status={status}
      className="relative grid h-full grid-rows-[auto_1fr] gap-3 overflow-hidden rounded-lg border bg-surface p-[0.8rem] text-foreground no-underline transition-[translate,box-shadow,border-color] duration-300 ease-out-soft hover:-translate-y-1 hover:border-primary/45 hover:text-foreground hover:shadow-card"
    >
      {cover}
      <span className="absolute start-[1.15rem] top-[1.15rem] rounded-full border border-scrim-foreground/20 bg-scrim px-[0.6rem] py-[0.3rem] text-2xs font-bold tracking-[0.04em] text-scrim-foreground uppercase backdrop-blur-[10px]">
        {kind}
      </span>
      <div className="grid h-32 min-h-0 grid-rows-[auto_auto_1fr] gap-[0.9rem] px-[0.15rem] pt-[0.1rem] pb-[0.2rem]">
        <h3 className="text-lead leading-tight" lang={lang}>
          <span className={clamp2}>{title}</span>
        </h3>
        <div className="flex flex-nowrap gap-[0.35rem] overflow-hidden [&>*]:shrink-0">{tags}</div>
        <time dateTime={when} className="mt-auto pt-[0.3rem] text-step--1 text-muted-foreground">
          {timeAgo(when)}
        </time>
      </div>
    </NavLink>
  );
}

const picture = cn(coverTile, "rounded-lg");

const ICON: Partial<Record<Entry["kind"], LucideIcon>> = {
  model3d: Box,
  composition: Shapes,
  creative_project: Clapperboard,
  notebook: BookOpen,
  taught: GraduationCap,
};

/** One card in My creations: a song, an image, a video or speech, each linking to its own page. */
export function CreationCard({
  entry,
  note,
  nav,
  onOpen,
}: {
  entry: Entry;
  note?: string;
  nav: CreationsNav;
  /** open the entry in the Library's detail view; without it a card goes to the entry's tool */
  onOpen?: (entry: Entry) => void;
}) {
  const noteTag = note ? <Badge variant="tag">{note}</Badge> : null;
  const Icon = ICON[entry.kind];
  if (Icon) {
    // the kinds that live in their own tools: an icon, the name and what it is
    const row = toRow(entry);
    return (
      <Card
        nav={nav}
        to={entry}
        onOpen={onOpen}
        kind={KIND_LABEL[entry.kind]}
        status={row.status}
        cover={
          <div
            className={cn(picture, "grid place-items-center p-4 text-primary-foreground")}
            aria-hidden="true"
          >
            <Icon className="size-10" />
          </div>
        }
        title={row.title}
        tags={
          <>
            {row.detail ? <Badge variant="tag">{row.detail.slice(0, 40)}</Badge> : null}
            {noteTag}
          </>
        }
        when={entry.createdAt}
      />
    );
  }
  if (entry.kind === "speech") {
    const { speech } = entry;
    return (
      <Card
        nav={nav}
        to={entry}
        onOpen={onOpen}
        kind="Speech"
        cover={
          <div
            className={cn(picture, "grid place-items-center p-4 text-primary-foreground")}
            aria-hidden="true"
          >
            <AudioLines className="size-10" />
          </div>
        }
        title={speech.text}
        tags={
          <>
            <Badge variant="tag">{speech.voice}</Badge>
            {noteTag}
          </>
        }
        when={speech.created_at}
      />
    );
  }
  if (entry.kind === "transcript") {
    const { transcript } = entry;
    return (
      <Card
        nav={nav}
        to={entry}
        onOpen={onOpen}
        kind="Transcript"
        cover={
          <div
            className={cn(picture, "grid place-items-center p-4 text-primary-foreground")}
            aria-hidden="true"
          >
            <Mic className="size-10" />
          </div>
        }
        title={transcript.title}
        tags={
          <>
            <Badge variant="tag">{clock(transcript.seconds)}</Badge>
            {noteTag}
          </>
        }
        when={transcript.created_at}
      />
    );
  }
  if (entry.kind === "lipsync")
    return (
      <LipSyncCard lipsync={entry.lipsync} entry={entry} nav={nav} note={note} onOpen={onOpen} />
    );
  if (entry.kind === "video")
    return <VideoCard video={entry.video} entry={entry} nav={nav} note={note} onOpen={onOpen} />;
  if (entry.kind === "image") {
    return (
      <Card
        nav={nav}
        to={entry}
        onOpen={onOpen}
        kind={KIND_LABEL.image}
        cover={<img className={picture} src={entry.image.thumb_url} alt="" loading="lazy" />}
        title={entry.image.prompt}
        tags={noteTag}
        when={entry.createdAt}
      />
    );
  }
  if (entry.kind !== "song") return null; // every other kind is drawn above
  return (
    <Card
      nav={nav}
      to={entry}
      onOpen={onOpen}
      kind="Music"
      cover={
        <div
          className={cn(picture, "grid place-items-center p-4 text-primary-foreground")}
          aria-hidden="true"
        >
          <AudioLines className="size-10" />
        </div>
      }
      title={entry.song.title}
      tags={
        <>
          {styleTags(entry.song.style)
            .slice(0, 3)
            .map((tag) => (
              <Badge variant="tag" key={tag}>
                {tag}
              </Badge>
            ))}
          {noteTag}
        </>
      }
      when={entry.createdAt}
    />
  );
}

/** A clip: its poster when ready, a "making" card while it is, and the reason when it failed. */
function VideoCard({
  video,
  entry,
  nav,
  note,
  onOpen,
}: {
  video: VideoSummary;
  entry: Entry;
  nav: CreationsNav;
  note?: string;
  onOpen?: (entry: Entry) => void;
}) {
  return (
    <Card
      nav={nav}
      to={entry}
      onOpen={onOpen}
      kind="Video"
      status={video.status}
      cover={
        video.status === "done" && video.poster_url ? (
          <img className={picture} src={video.poster_url} alt="" loading="lazy" />
        ) : (
          <div
            className={cn(picture, "grid place-items-center text-primary-foreground")}
            aria-hidden="true"
          >
            {video.status === "working" ? <Spinner /> : null}
          </div>
        )
      }
      title={video.prompt}
      tags={
        video.status === "working" ? (
          <Badge variant="tag">Making your video…</Badge>
        ) : video.status === "failed" ? (
          <Badge variant="tag">Couldn't be made</Badge>
        ) : note ? (
          <Badge variant="tag">{note}</Badge>
        ) : null
      }
      when={video.created_at}
    />
  );
}

function LipSyncCard({
  lipsync,
  entry,
  nav,
  note,
  onOpen,
}: {
  lipsync: LipSyncEntry;
  entry: Entry;
  nav: CreationsNav;
  note?: string;
  onOpen?: (entry: Entry) => void;
}) {
  return (
    <Card
      nav={nav}
      to={entry}
      onOpen={onOpen}
      kind="Lip sync"
      cover={
        lipsync.poster_url ? (
          <img className={picture} src={lipsync.poster_url} alt="" loading="lazy" />
        ) : (
          <div className={picture} aria-hidden="true" />
        )
      }
      title={lipsync.text || "Lip sync"}
      tags={
        <>
          <Badge variant="tag">{clock(lipsync.seconds)}</Badge>
          {note ? <Badge variant="tag">{note}</Badge> : null}
        </>
      }
      when={lipsync.created_at}
    />
  );
}
