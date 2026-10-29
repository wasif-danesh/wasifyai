import type { ReactNode } from "react";

/**
 * The groups of models a person meets, named for what they want to do (ADR-0086). Each group is a picker:
 * every screen that needs a model of the group has the same button and the same panel.
 */
export type GroupId =
  | "chat"
  | "images"
  | "video"
  | "voice"
  | "listening"
  | "music"
  | "faces"
  | "documents"
  | "three_d";

export type Group = {
  id: GroupId;
  /** the title of the group on the Models page */
  title: string;
  /** the button when nothing is chosen: "Select image model" */
  select: string;
  /** what the group is, in a few words, for the Models page */
  about: string;
};

export const GROUPS: Group[] = [
  {
    id: "chat",
    title: "Chat",
    select: "Select chat model",
    about: "Answers your questions, writes and reads pictures",
  },
  {
    id: "images",
    title: "Images",
    select: "Select image model",
    about: "Makes and changes pictures",
  },
  { id: "video", title: "Video", select: "Select video model", about: "Makes short videos" },
  {
    id: "voice",
    title: "Voice",
    select: "Select voice model",
    about: "Speaks text, clones and changes voices",
  },
  {
    id: "listening",
    title: "Listening",
    select: "Select transcription model",
    about: "Turns speech into text",
  },
  {
    id: "music",
    title: "Music",
    select: "Select music model",
    about: "Makes songs and sounds, splits a song into parts",
  },
  {
    id: "faces",
    title: "Lip sync",
    select: "Select lip sync model",
    about: "Makes a picture talk",
  },
  {
    id: "documents",
    title: "Documents",
    select: "Select search model",
    about: "Lets notebooks read your documents",
  },
  {
    id: "three_d",
    title: "3D",
    select: "Select 3D model",
    about: "Turns a picture into a 3D model",
  },
];

export const groupOf = (id: GroupId): Group => GROUPS.find((g) => g.id === id) as Group;

/** The group a voice task belongs to: the screens name tasks, the picker names groups. */
export function groupOfTask(task: string): GroupId {
  if (task === "transcribe") return "listening";
  if (task === "music" || task === "sfx" || task === "separate") return "music";
  if (task === "lipsync") return "faces";
  return "voice";
}

/** `ready`: usable now. `needs_download`: files (and maybe an engine) to get first. `too_big`: will not run here. */
export type ChoiceState = "ready" | "needs_download" | "too_big" | "unavailable";

export type Fit = "fits" | "tight" | "too_big";

/** How much a person is told to look at first: the best choice for this computer, the others, the rest. */
export type Tier = "recommended" | "also" | "advanced";

export type ModelChoice = {
  id: string;
  title: string;
  /** one line, no jargon: what it does and what it is good at */
  plain: string;
  tier: Tier;
  state: ChoiceState;
  /** the model this group uses now */
  chosen: boolean;
  /** bytes of the model's own files still to fetch */
  downloadBytes: number;
  /** bytes of the engine this model needs and the computer lacks (once), and its name: "the image engine" */
  engineBytes: number;
  engineName: string | null;
  fit: Fit | null;
  fitReason: string | null;
  /** where it comes from: the app's own list, a file found on the computer, a running server */
  source: "app" | "found" | "server";
  /** the website the files come from, said in the download dialog: "huggingface.co" */
  from?: string | null;
  /** bytes this model takes on the computer when it is there (0 when not known) */
  sizeBytes?: number;
  /** the app can take it off the computer again */
  removable?: boolean;
  /** chat models: can read pictures */
  readsPictures?: boolean;
  /** why `unavailable`, in words */
  unavailableReason?: string | null;
};

export type ChoiceList = {
  choices: ModelChoice[];
  /** free disk space and memory, for the dialog and the order */
  diskFreeBytes: number | null;
  memoryBytes: number | null;
};

/** How far a "get and use" has got: the step in words, and how far through all of it (null: not known). */
export type GetProgress = { label: string; fraction: number | null };

/**
 * What a group needs from its owner (the window): the rows, choosing one that is ready, and getting one that is not.
 * `get` fetches the engine if missing, then the model, then chooses it, and rejects with a sentence on failure.
 */
export type ChoicesApi = {
  list(): Promise<ChoiceList>;
  choose(id: string): Promise<void>;
  get(id: string, onProgress: (p: GetProgress) => void, signal: AbortSignal): Promise<void>;
  /** Take a model off the computer (the Models page); absent where the app cannot. */
  remove?(id: string): Promise<void>;
  /** what "More models" shows: search, model folders, Hugging Face (the window gives its own) */
  more?: ReactNode;
};
