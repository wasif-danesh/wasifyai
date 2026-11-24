/**
 * The groups of models a person meets, named for what they want to do (ADR-0086). Each group is a picker:
 * every screen that needs a model of the group has the same button and the same panel.
 */
export type GroupId =
  | "chat"
  | "code"
  | "images"
  | "video"
  | "voice"
  | "listening"
  | "music"
  | "faces"
  | "documents"
  | "three_d"
  | "train";

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
    id: "code",
    title: "Code",
    select: "Select coding model",
    about: "Reads, changes and runs code in a project",
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
  {
    id: "train",
    title: "Training",
    select: "Select where to teach",
    about: "Teaches your own looks from your pictures",
  },
];

export const groupOf = (id: GroupId): Group => GROUPS.find((g) => g.id === id) as Group;

/** The group a voice task belongs to: the screens name tasks, the picker names groups. */
export function groupOfTask(task: string): GroupId {
  if (task === "transcribe") return "listening";
  if (["music", "sfx", "separate", "musicedit"].includes(task)) return "music";
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
  /** `needs_download` whose files another tool already has on the computer ("ComfyUI"): getting it uses them where
   * they are, nothing of the model is downloaded (`downloadBytes` is then 0) */
  foundIn?: string | null;
  /** a cloud model on the person's key (ADR-0095, amendment of 2026-11-11): shown under Cloud, not on this computer.
   * "agent": a model of the person's own agent program, on their plan (ADR-0107): shown under Your agent, with
   * `provider` the program's id and `providerTitle` its name ("Claude Code") */
  place?: "cloud" | "agent";
  /** a cloud model's provider: its id and name ("fal.ai") */
  provider?: string;
  providerTitle?: string;
  /** a cloud model's price as the provider lists it, in words */
  price?: string;
  /** how long a cloud model took when measured, in words ("about 5 s per second of video") */
  speed?: string;
  /** a cloud model's key worked when last tested */
  works?: boolean;
  /** what a cloud model can do with the keys there are ("image.inpaint"), for its screen to offer */
  can?: string[];
  /** the id the screen's engine knows a cloud model by while it is in use (`key:lipsync`), when not this row's id */
  engineId?: string;
  /** a caution shown as a badge on the row: "May not manage coding well" */
  note?: string | null;
  /** said after the row's state: "about 24 GB of memory while it works" */
  detail?: string | null;
  /** a button under an `unavailable` row that puts it right: "Open the Model hub" */
  fix?: { label: string; run: () => void } | null;
};

/** A line under the rows, with a link: "Coding and chat use the same model…" */
export type ChoiceFoot = { text: string; link?: { label: string; run: () => void } };

export type ChoiceList = {
  choices: ModelChoice[];
  /** free disk space and memory, for the dialog and the order */
  diskFreeBytes: number | null;
  memoryBytes: number | null;
  /** lines under the rows of On this computer, where the model is chosen somewhere else (`ChoicesApi.elsewhere`) */
  foot?: ChoiceFoot[];
};

/** How far a "get and use" has got: the step in words, and how far through all of it (null: not known). */
export type GetProgress = { label: string; fraction: number | null };

/** One of the person's own agent programs, as the Your agent tab shows it (ADR-0107). */
export type AgentProgram = {
  id: string;
  title: string;
  /** "Your Claude plan" */
  payer: string;
  /** the account the person signs in with, in words: "Claude", "ChatGPT" */
  account: string;
  signedIn: boolean;
  /** the plan's name ("Max"); empty when not known */
  plan: string;
  signingIn: boolean;
  /** the sign-in page the program printed, for when no page opened by itself */
  page: string;
};

/** The agent programs as one optional part: set up or not, and how far a setup is. */
export type AgentSetup =
  | { state: "not_installed"; bytes: number }
  | { state: "installing"; fraction: number | null; label: string }
  | { state: "installed"; version: string; bytes: number }
  | { state: "failed"; message: string }
  | { state: "unsupported"; reason: string };

/** What the Your agent tab needs from the window: the programs, setting them up, and their own sign-in. */
export type AgentsApi = {
  programs(): Promise<{ setup: AgentSetup; programs: AgentProgram[] }>;
  setUp(bytes: number): Promise<void>;
  remove(): Promise<void>;
  signIn(id: string): Promise<void>;
  cancelSignIn(id: string): Promise<void>;
};

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
  /** the group can run on cloud models with the person's keys: the picker shows a Cloud tab. `product` names it
   * in words ("Lip sync"); `setUp` opens Settings › Your keys */
  cloud?: { product: string; setUp?: () => void };
  /** the group can run on the person's own agent programs (Code, ADR-0107; the chat, ADR-0110): the picker shows a
   * Your agent tab, or a tab named `agentsTab` ("Your plan") */
  agents?: AgentsApi;
  agentsTab?: string;
  /** the tab's own lines (`intro` before setting up, `foot` under the programs); Code's when left out */
  agentsWords?: { intro: string; foot: string };
  /** the group's model on this computer is chosen somewhere else (Code: the Model hub, LM2). On this computer then
   * lists every row, ready or not, under `heading` with a link to that place, and the list's `foot` under them */
  elsewhere?: {
    heading: string;
    change?: { label: string; run: () => void };
  };
};
