import { clock } from "./format";

// What My creations shows: one entry per song, image or video, whatever product made it (ADR-0040).
import type {
  ImageSummary,
  LipSyncSummary,
  SongSummary,
  SpeechSummary,
  TranscriptSummary,
  VideoSummary,
} from "@wasifyai/contracts";

export type Entry =
  | { kind: "song"; id: string; createdAt: string; song: SongSummary }
  | { kind: "image"; id: string; createdAt: string; image: ImageSummary }
  | { kind: "video"; id: string; createdAt: string; video: VideoSummary }
  | { kind: "speech"; id: string; createdAt: string; speech: SpeechSummary }
  | { kind: "transcript"; id: string; createdAt: string; transcript: TranscriptSummary }
  | { kind: "lipsync"; id: string; createdAt: string; lipsync: LipSyncSummary };

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
export function kindOf(filter: Filter): Entry["kind"] | undefined {
  const kinds = {
    songs: "song",
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
  href: string;
  createdAt: string;
  status: "done" | "working" | "failed";
};

/** One entry as a table row: what it is, what it says, where it opens and whether it is ready. */
export function toRow(entry: Entry): Row {
  const base = { key: `${entry.kind}:${entry.id}`, kind: entry.kind, createdAt: entry.createdAt };
  switch (entry.kind) {
    case "song":
      return {
        ...base,
        kindLabel: "Song",
        title: entry.song.title,
        detail: entry.song.style ?? "",
        href: `/music/songs/${entry.id}`,
        status: "done",
      };
    case "image":
      return {
        ...base,
        kindLabel: "Image",
        title: entry.image.prompt,
        detail: "",
        href: `/image/creations/${entry.id}`,
        status: "done",
      };
    case "video":
      return {
        ...base,
        kindLabel: "Video",
        title: entry.video.prompt,
        detail: "",
        href: `/video/creations/${entry.id}`,
        status: entry.video.status,
      };
    case "speech":
      return {
        ...base,
        kindLabel: "Speech",
        title: entry.speech.text,
        detail: `${entry.speech.language_name} · ${entry.speech.gender === "male" ? "Male" : "Female"}, ${entry.speech.voice}`,
        href: `/text-to-speech/creations/${entry.id}`,
        status: "done",
      };
    case "transcript":
      return {
        ...base,
        kindLabel: "Transcript",
        title: entry.transcript.title || "Transcribing…",
        detail: [entry.transcript.language_name, clock(entry.transcript.seconds)]
          .filter(Boolean)
          .join(" · "),
        href: `/speech-to-text/creations/${entry.id}`,
        status: entry.transcript.status,
      };
    case "lipsync":
      return {
        ...base,
        kindLabel: "Lip sync",
        title: entry.lipsync.text || entry.lipsync.style || "Lip sync",
        detail: clock(entry.lipsync.seconds),
        href: `/lip-sync/creations/${entry.id}`,
        status: entry.lipsync.status,
      };
  }
}
