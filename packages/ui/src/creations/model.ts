import type {
  BuilderProject,
  ImageSummary,
  LipSyncCard,
  Model3d,
  NotebookSummary,
  SongCard,
  SpeechCard,
  TrainedModel,
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
  | { kind: "lipsync"; id: string; createdAt: string; lipsync: LipSyncCard }
  | { kind: "model3d"; id: string; createdAt: string; model3d: Model3d }
  | { kind: "composition"; id: string; createdAt: string; composition: BuilderProject }
  | { kind: "notebook"; id: string; createdAt: string; notebook: NotebookSummary }
  | { kind: "taught"; id: string; createdAt: string; taught: TrainedModel };

export type Filter =
  | "all"
  | "songs"
  | "images"
  | "videos"
  | "speeches"
  | "transcripts"
  | "lipsyncs"
  | "models3d"
  | "compositions"
  | "notebooks"
  | "taught";

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
    models3d: "model3d",
    compositions: "composition",
    notebooks: "notebook",
    taught: "taught",
  } as const;
  return filter === "all" ? undefined : kinds[filter];
}

/** The entry kind a filter shows, or null for "all". */
export const FILTER_KIND: Record<Filter, Entry["kind"] | null> = {
  all: null,
  songs: "song",
  images: "image",
  videos: "video",
  speeches: "speech",
  transcripts: "transcript",
  lipsyncs: "lipsync",
  models3d: "model3d",
  compositions: "composition",
  notebooks: "notebook",
  taught: "taught",
};

/** What each kind is called in the Library, one word a person would use (design/DESIGN.md's nouns). */
export const KIND_LABEL: Record<Entry["kind"], string> = {
  song: "Music",
  image: "Picture",
  video: "Video",
  speech: "Speech",
  transcript: "Transcript",
  lipsync: "Lip sync",
  model3d: "3D model",
  composition: "Motion graphics",
  notebook: "Notebook",
  taught: "Taught model",
};

/** The search index's kind for an entry kind (the index calls music a track; taught models are three kinds). */
export function indexKindOf(kind: Entry["kind"]): string {
  return kind === "song" ? "track" : kind;
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
        kindLabel: KIND_LABEL.song,
        title: entry.song.title,
        detail: entry.song.style ?? "",
        status: "done",
      };
    case "image":
      return {
        ...base,
        kindLabel: KIND_LABEL.image,
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
    case "model3d":
      return {
        ...base,
        kindLabel: KIND_LABEL.model3d,
        title: entry.model3d.title || entry.model3d.prompt || "3D model",
        detail: entry.model3d.prompt,
        status:
          entry.model3d.status === "done"
            ? "done"
            : entry.model3d.status === "failed"
              ? "failed"
              : "working",
      };
    case "composition":
      return {
        ...base,
        kindLabel: KIND_LABEL.composition,
        title: entry.composition.title || "Motion graphics",
        detail: entry.composition.template,
        status: "done",
      };
    case "notebook":
      return {
        ...base,
        kindLabel: KIND_LABEL.notebook,
        title: entry.notebook.title || "Notebook",
        detail: `${entry.notebook.sources} ${entry.notebook.sources === 1 ? "source" : "sources"}`,
        status: "done",
      };
    case "taught":
      return {
        ...base,
        kindLabel: KIND_LABEL.taught,
        title: entry.taught.name,
        detail: entry.taught.card?.base_title ?? entry.taught.base,
        status: "done",
      };
  }
}

export type MakeScreen = "music" | "image" | "video" | "speech" | "transcribe" | "lipsync";

/** What the detail view can hand an entry to (the app opens that tool with it chosen, ADR-0093 U8). */
export type UseAction =
  | "edit" // a picture into Edit
  | "animate" // a picture into Video's Animate
  | "extend" // a clip into Extend
  | "again" // music made again with its own seed, or a picture's recipe into Create
  | "split" // music into Split into parts
  | "convert" // a recording or speech into Change a voice
  | "speechedit"; // a recording or speech into Edit speech

/** How My creations goes elsewhere: each app knows its own screens (the web has addresses, the desktop a router). */
export type CreationsNav = {
  /** open the screen that holds an entry */
  open(entry: Entry): void;
  /** open a screen that makes something new */
  make(screen: MakeScreen): void;
  /** the address of a place, where the app has addresses (the web): a card is then a real link */
  href?(target: Entry | MakeScreen): string;
  /** hand an entry to a tool (Edit this, Animate this, Extend this…); actions the app leaves out are not offered */
  use?(entry: Entry, action: UseAction): void;
  /** which actions `use` takes for an entry */
  canUse?(entry: Entry, action: UseAction): boolean;
};
