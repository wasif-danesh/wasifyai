import type {
  ImageSummary,
  LipSyncCard,
  SongCard,
  SpeechCard,
  TranscriptCard,
  VideoSummary,
} from "@wasifyai/client";
import { clock } from "../voice/format";

// What My creations shows: one entry per piece of music, image, video, speech, transcript or lip sync (ADR-0040).

export type Entry =
  | { kind: "song"; id: string; createdAt: string; song: SongCard }
  | { kind: "image"; id: string; createdAt: string; image: ImageSummary }
  | { kind: "video"; id: string; createdAt: string; video: VideoSummary }
  | { kind: "speech"; id: string; createdAt: string; speech: SpeechCard }
  | { kind: "transcript"; id: string; createdAt: string; transcript: TranscriptCard }
  | { kind: "lipsync"; id: string; createdAt: string; lipsync: LipSyncCard };

export type Filter =
  | "all"
  | "songs"
  | "images"
  | "videos"
  | "speeches"
  | "transcripts"
  | "lipsyncs";

/** A search needs two characters, except in Chinese, Japanese and Korean, where one character can be a
 * whole word (龙 is "dragon"). The API applies the same rule. */
export function longEnough(query: string): boolean {
  const q = query.trim();
  return q.length >= 2 || /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]/.test(q);
}

/** The `kind` the search API takes for a filter, or undefined for "all". */
export function kindOf(filter: Filter): string | undefined {
  const kinds = {
    songs: "track", // the index calls the voice product's music a track
    images: "image",
    videos: "video",
    speeches: "speech",
    transcripts: "transcript",
    lipsyncs: "lipsync",
  } as const;
  return filter === "all" ? undefined : kinds[filter];
}

export type Row = {
  key: string;
  kind: Entry["kind"];
  kindLabel: string;
  title: string;
  detail: string;
  entry: Entry;
  createdAt: string;
  status: "done" | "working" | "failed";
};

/** One entry as a table row: what it is, what it says, where it opens and whether it is ready. */
export function toRow(entry: Entry): Row {
  const base = {
    key: `${entry.kind}:${entry.id}`,
    kind: entry.kind,
    entry,
    createdAt: entry.createdAt,
  };
  switch (entry.kind) {
    case "song":
      return {
        ...base,
        kindLabel: "Music",
        title: entry.song.title,
        detail: entry.song.style ?? "",
        status: "done",
      };
    case "image":
      return {
        ...base,
        kindLabel: "Image",
        title: entry.image.prompt,
        detail: "",
        status: "done",
      };
    case "video":
      return {
        ...base,
        kindLabel: "Video",
        title: entry.video.prompt,
        detail: "",
        status: entry.video.status,
      };
    case "speech":
      return {
        ...base,
        kindLabel: "Speech",
        title: entry.speech.text,
        detail: entry.speech.voice,
        status: "done",
      };
    case "transcript":
      return {
        ...base,
        kindLabel: "Transcript",
        title: entry.transcript.title || "Transcribing…",
        detail: clock(entry.transcript.seconds),
        status: entry.transcript.status,
      };
    case "lipsync":
      return {
        ...base,
        kindLabel: "Lip sync",
        title: entry.lipsync.text || "Lip sync",
        detail: clock(entry.lipsync.seconds),
        status: entry.lipsync.status,
      };
  }
}

export type MakeScreen = "music" | "image" | "video" | "speech" | "transcribe" | "lipsync";

/** How My creations goes elsewhere: each app knows its own screens (the web has addresses, the desktop a router). */
export type CreationsNav = {
  /** open the screen that holds an entry */
  open(entry: Entry): void;
  /** open a screen that makes something new */
  make(screen: MakeScreen): void;
  /** the address of a place, where the app has addresses (the web): a card is then a real link */
  href?(target: Entry | MakeScreen): string;
};
