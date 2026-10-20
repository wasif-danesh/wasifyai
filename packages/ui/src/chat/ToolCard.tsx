"use client";

import type { ChatPart, ImageSummary, ImagesApi } from "@wasifyai/client";
import { BookOpen, FileText, Globe, ImageIcon, Music, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../components/button";
import { Spinner } from "../components/spinner";

type Tool = Extract<ChatPart, { type: "tool" }>;

/** A piece of music the assistant made, as the card needs it. */
export type TrackLookup = (id: string) => Promise<{ title: string; audio_url: string }>;

export type ToolCardProps = {
  tool: Tool;
  images: ImagesApi;
  /** Reads a track made by `make_music` so it can be played in the chat. */
  tracks?: TrackLookup;
  /** Open a creation in its own screen (the library for an image). */
  onOpenCreation?: (kind: string, id: string) => void;
};

function Picture({
  imageId,
  images,
  onOpen,
}: {
  imageId: string;
  images: ImagesApi;
  onOpen?: () => void;
}) {
  const [image, setImage] = useState<ImageSummary | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let gone = false;
    images
      .get(imageId)
      .then((i) => !gone && setImage(i))
      .catch(() => !gone && setMissing(true));
    return () => {
      gone = true;
    };
  }, [imageId, images]);
  if (missing)
    return <p className="text-muted-foreground text-sm">This picture is no longer there.</p>;
  if (!image) return <div className="aspect-square w-64 animate-pulse rounded-lg bg-muted" />;
  return (
    <figure className="m-0 grid w-fit max-w-sm gap-2">
      <img
        src={image.image_url}
        alt={image.prompt}
        width={image.width || undefined}
        height={image.height || undefined}
        className="h-auto max-h-96 w-auto max-w-full rounded-lg border object-contain"
      />
      <figcaption className="flex flex-wrap items-center gap-2 text-muted-foreground text-xs">
        <span className="min-w-0 max-w-full truncate">{image.prompt}</span>
        {onOpen ? (
          <Button type="button" size="sm" variant="outline" onClick={onOpen}>
            Open in the library
          </Button>
        ) : null}
      </figcaption>
    </figure>
  );
}

function MusicPlayer({
  trackId,
  tracks,
  onOpen,
}: {
  trackId: string;
  tracks?: TrackLookup;
  onOpen?: () => void;
}) {
  const [track, setTrack] = useState<{ title: string; audio_url: string } | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    if (!tracks) return;
    let gone = false;
    tracks(trackId)
      .then((t) => !gone && setTrack(t))
      .catch(() => !gone && setMissing(true));
    return () => {
      gone = true;
    };
  }, [trackId, tracks]);
  if (missing)
    return <p className="text-muted-foreground text-sm">This music is no longer there.</p>;
  if (!tracks) return <p className="text-muted-foreground text-sm">Saved to Your music.</p>;
  if (!track) return <div className="h-14 w-72 animate-pulse rounded-lg bg-muted" />;
  return (
    <figure className="m-0 grid w-full max-w-md gap-2 rounded-lg border p-3">
      <figcaption className="flex items-center gap-2 text-sm">
        <Music className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate font-medium">{track.title}</span>
        {onOpen ? (
          <Button type="button" size="sm" variant="outline" onClick={onOpen}>
            Open in Your music
          </Button>
        ) : null}
      </figcaption>
      {/* biome-ignore lint/a11y/useMediaCaption: music */}
      <audio controls src={track.audio_url} className="h-10 w-full" aria-label={track.title} />
    </figure>
  );
}

/** A picture being made, then shown with a way to open it. */
export function ImageToolCard({ tool, images, tracks, onOpenCreation }: ToolCardProps) {
  if (tool.status === "running") {
    const queued = tool.jobStatus === "queued";
    const pct = typeof tool.progress === "number" ? Math.round(tool.progress * 100) : null;
    return (
      <output className="flex items-center gap-3 rounded-lg border p-3 text-sm">
        <Spinner />
        <span>
          {queued
            ? tool.queuePosition && tool.queuePosition > 1
              ? `Waiting for a turn, place ${tool.queuePosition}`
              : "Waiting for a turn"
            : pct !== null && pct > 0
              ? `Making your picture, ${pct}%`
              : "Making your picture"}
        </span>
      </output>
    );
  }
  if (tool.status === "ok" && typeof tool.output?.image_id === "string") {
    const id = tool.output.image_id;
    return (
      <Picture
        imageId={id}
        images={images}
        onOpen={onOpenCreation ? () => onOpenCreation("image", id) : undefined}
      />
    );
  }
  return (
    <p className="flex items-center gap-2 rounded-lg border p-3 text-sm">
      <ImageIcon className="size-4 shrink-0" aria-hidden="true" />
      {tool.status === "refused"
        ? String(tool.output?.message ?? "That picture was not made.")
        : "The picture could not be made."}
    </p>
  );
}

/** A piece of music being made, then a player. */
export function MusicToolCard({ tool, images, tracks, onOpenCreation }: ToolCardProps) {
  if (tool.status === "running") {
    return (
      <output className="flex items-center gap-3 rounded-lg border p-3 text-sm">
        <Spinner /> Making your music
      </output>
    );
  }
  if (tool.status === "ok" && typeof tool.output?.track_id === "string") {
    const id = tool.output.track_id;
    return (
      <MusicPlayer
        trackId={id}
        tracks={tracks}
        onOpen={onOpenCreation ? () => onOpenCreation("track", id) : undefined}
      />
    );
  }
  return (
    <p className="flex items-center gap-2 rounded-lg border p-3 text-sm">
      <Music className="size-4 shrink-0" aria-hidden="true" />
      {tool.status === "refused"
        ? String(tool.output?.message ?? "That music was not made.")
        : "The music could not be made."}
    </p>
  );
}

/** What a search of the library found. */
export function LibrarySearchCard({ tool, images, tracks, onOpenCreation }: ToolCardProps) {
  if (tool.status === "running") {
    return (
      <output className="flex items-center gap-3 rounded-lg border p-3 text-sm">
        <Spinner /> Looking through your library
      </output>
    );
  }
  const results = Array.isArray(tool.output?.results)
    ? (tool.output.results as { kind: string; id: string; text?: string }[])
    : [];
  return (
    <div className="grid gap-2 rounded-lg border p-3 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <Search className="size-4" aria-hidden="true" />
        {results.length ? `Found ${results.length} in your library` : "Nothing matched"}
      </p>
      {results.length ? (
        <ul className="grid gap-1">
          {results.map((r) => (
            <li key={`${r.kind}-${r.id}`} className="flex items-center gap-2">
              <span className="truncate">{r.text || r.id}</span>
              <span className="text-muted-foreground text-xs">{r.kind}</span>
              {onOpenCreation ? (
                <button
                  type="button"
                  className="ms-auto text-xs underline underline-offset-4"
                  onClick={() => onOpenCreation(r.kind, r.id)}
                >
                  Open
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** What a search of the notebooks found. */
export function NotebookSearchCard({ tool, images, tracks, onOpenCreation }: ToolCardProps) {
  if (tool.status === "running") {
    return (
      <output className="flex items-center gap-3 rounded-lg border p-3 text-sm">
        <Spinner /> Looking through your notebooks
      </output>
    );
  }
  if (tool.status !== "ok") {
    return (
      <p className="flex items-center gap-2 rounded-lg border p-3 text-sm">
        <BookOpen className="size-4 shrink-0" aria-hidden="true" />
        {String(tool.output?.message ?? "Your notebooks could not be searched.")}
      </p>
    );
  }
  const results = Array.isArray(tool.output?.results)
    ? (tool.output.results as {
        notebook_id: string;
        notebook: string;
        document_id: string;
        title: string;
        snippet?: string;
      }[])
    : [];
  return (
    <div className="grid gap-2 rounded-lg border p-3 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <BookOpen className="size-4" aria-hidden="true" />
        {results.length ? "From your notebooks" : "Nothing in your notebooks matched"}
      </p>
      {results.length ? (
        <ul className="grid gap-2">
          {results.map((r) => (
            <li
              key={`${r.notebook_id}-${r.document_id}-${r.snippet ?? ""}`}
              className="grid gap-0.5"
            >
              <span className="flex items-center gap-2">
                <span className="min-w-0 truncate">{r.title}</span>
                <span className="truncate text-muted-foreground text-xs">{r.notebook}</span>
                {onOpenCreation ? (
                  <button
                    type="button"
                    className="ms-auto shrink-0 text-xs underline underline-offset-4"
                    onClick={() => onOpenCreation("notebook", r.notebook_id)}
                  >
                    Open notebook
                  </button>
                ) : null}
              </span>
              {r.snippet ? (
                <span className="line-clamp-2 text-muted-foreground text-xs">{r.snippet}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** A web address that is safe to link to: http or https only, never a script or a file. */
function webHref(url: unknown): string | null {
  if (typeof url !== "string") return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

/** A link to a page on the internet: it opens in the person's own browser, never inside the app. */
function SourceLink({ url, children }: { url: unknown; children: string }) {
  const href = webHref(url);
  if (!href) return <span className="min-w-0 truncate">{children}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      data-external=""
      className="min-w-0 truncate font-medium underline underline-offset-4"
    >
      {children}
    </a>
  );
}

/** What a search of the web found: the sources, with their sites, so the answer can be checked. */
export function WebSearchCard({ tool }: ToolCardProps) {
  if (tool.status === "running") {
    return (
      <output className="flex items-center gap-3 rounded-lg border p-3 text-sm">
        <Spinner /> Searching the web
      </output>
    );
  }
  if (tool.status !== "ok") {
    return (
      <p className="flex items-center gap-2 rounded-lg border p-3 text-sm">
        <Globe className="size-4 shrink-0" aria-hidden="true" />
        {String(tool.output?.message ?? "The web could not be searched.")}
      </p>
    );
  }
  const results = Array.isArray(tool.output?.results)
    ? (tool.output.results as { title: string; url: string; site: string; snippet?: string }[])
    : [];
  const via = typeof tool.output?.provider_title === "string" ? tool.output.provider_title : "";
  return (
    <div className="grid gap-2 rounded-lg border p-3 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <Globe className="size-4" aria-hidden="true" />
        {results.length
          ? `Sources from the web${via ? ` (${via})` : ""}`
          : "Nothing found on the web"}
      </p>
      {results.length ? (
        <ol className="grid list-none gap-2 p-0">
          {results.map((r) => (
            <li key={r.url} className="grid gap-0.5">
              <span className="flex items-center gap-2">
                <SourceLink url={r.url}>{r.title}</SourceLink>
                <span className="ms-auto shrink-0 text-muted-foreground text-xs">{r.site}</span>
              </span>
              {r.snippet ? (
                <span className="line-clamp-2 text-muted-foreground text-xs">{r.snippet}</span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

/** A page the assistant read: its title and site, a link to it, and the start of what it said. */
export function WebReadCard({ tool }: ToolCardProps) {
  if (tool.status === "running") {
    return (
      <output className="flex items-center gap-3 rounded-lg border p-3 text-sm">
        <Spinner /> Reading a web page
      </output>
    );
  }
  if (tool.status !== "ok") {
    return (
      <p className="flex items-center gap-2 rounded-lg border p-3 text-sm">
        <FileText className="size-4 shrink-0" aria-hidden="true" />
        {String(tool.output?.message ?? "That page could not be read.")}
      </p>
    );
  }
  const o = tool.output ?? {};
  const title = String(o.title || o.site || "Web page");
  return (
    <div className="grid gap-1 rounded-lg border p-3 text-sm">
      <p className="flex items-center gap-2">
        <FileText className="size-4 shrink-0" aria-hidden="true" />
        <SourceLink url={o.final_url ?? o.url}>{title}</SourceLink>
        <span className="ms-auto shrink-0 text-muted-foreground text-xs">
          {String(o.site ?? "")}
        </span>
      </p>
      {o.excerpt ? (
        <p className="line-clamp-3 text-muted-foreground text-xs">{String(o.excerpt)}</p>
      ) : null}
      {o.truncated ? (
        <p className="text-muted-foreground text-xs">Only the start of this page was read.</p>
      ) : null}
    </div>
  );
}

/** A tool the assistant used, as part of its answer: a picture being made and then shown, or what a
 * search found. */
export function ToolCard(props: ToolCardProps) {
  switch (props.tool.name) {
    case "generate_image":
      return <ImageToolCard {...props} />;
    case "make_music":
      return <MusicToolCard {...props} />;
    case "search_creations":
      return <LibrarySearchCard {...props} />;
    case "search_notebooks":
      return <NotebookSearchCard {...props} />;
    case "web_search":
      return <WebSearchCard {...props} />;
    case "web_read":
      return <WebReadCard {...props} />;
    default:
      return null;
  }
}
