import { Equaliser } from "@/components/Logo";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import type { Entry } from "@/lib/creations";
import { clock, styleTags, timeAgo } from "@/lib/format";
import { clamp2, coverTile } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { LipSyncCard as LipSyncEntry } from "@/lib/voice-cards";
import type { VideoSummary } from "@wasifyai/contracts";
import { Mic } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

/** One card in My creations: a cover, what kind it is, a title, a few tags and when it was made. */
function Card({
  href,
  kind,
  cover,
  title,
  tags,
  when,
  lang,
  status,
}: {
  href: string;
  kind: string;
  cover: ReactNode;
  title: string;
  tags?: ReactNode;
  when: string;
  lang?: string;
  status?: string;
}) {
  return (
    <Link
      href={href}
      data-status={status}
      className="relative grid h-full grid-rows-[auto_1fr] gap-3 overflow-hidden rounded-lg border bg-surface p-[0.8rem] text-foreground no-underline transition-[translate,box-shadow,border-color] duration-300 ease-out-soft hover:-translate-y-1 hover:border-primary/45 hover:text-foreground hover:shadow-card"
    >
      {cover}
      <span className="absolute start-[1.15rem] top-[1.15rem] rounded-full border border-white/20 bg-[oklch(20%_0.02_280/0.72)] px-[0.6rem] py-[0.3rem] text-[0.7rem] font-bold tracking-[0.04em] text-white uppercase backdrop-blur-[10px]">
        {kind}
      </span>
      <div className="grid h-32 min-h-0 grid-rows-[auto_auto_1fr] gap-[0.9rem] px-[0.15rem] pt-[0.1rem] pb-[0.2rem]">
        <h3 className="text-[1.05rem] leading-tight" lang={lang}>
          <span className={clamp2}>{title}</span>
        </h3>
        <div className="flex flex-nowrap gap-[0.35rem] overflow-hidden [&>*]:shrink-0">{tags}</div>
        <time dateTime={when} className="mt-auto pt-[0.3rem] text-step--1 text-muted-foreground">
          {timeAgo(when)}
        </time>
      </div>
    </Link>
  );
}

const picture = cn(coverTile, "rounded-lg");

/** One card in My creations: a song, an image, a video or speech, each linking to its own page. */
export function CreationCard({ entry, note }: { entry: Entry; note?: string }) {
  const noteTag = note ? <Badge variant="tag">{note}</Badge> : null;
  if (entry.kind === "speech") {
    const { speech } = entry;
    return (
      <Card
        href="/voice/speak"
        kind="Speech"
        cover={
          <div
            className={cn(picture, "grid place-items-center p-4 text-primary-foreground")}
            aria-hidden="true"
          >
            <Equaliser still />
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
        href="/voice/transcribe"
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
  if (entry.kind === "lipsync") return <LipSyncCard lipsync={entry.lipsync} note={note} />;
  if (entry.kind === "video") return <VideoCard video={entry.video} note={note} />;
  if (entry.kind === "image") {
    return (
      <Card
        href={`/image/creations/${entry.id}`}
        kind="Image"
        cover={<img className={picture} src={entry.image.thumb_url} alt="" loading="lazy" />}
        title={entry.image.prompt}
        tags={noteTag}
        when={entry.createdAt}
      />
    );
  }
  return (
    <Card
      href="/voice/tracks"
      kind="Music"
      cover={
        <div
          className={cn(picture, "grid place-items-center p-4 text-primary-foreground")}
          aria-hidden="true"
        >
          <Equaliser still />
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
function VideoCard({ video, note }: { video: VideoSummary; note?: string }) {
  return (
    <Card
      href={`/video/creations/${video.id}`}
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

function LipSyncCard({ lipsync, note }: { lipsync: LipSyncEntry; note?: string }) {
  return (
    <Card
      href="/voice/lipsync"
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
