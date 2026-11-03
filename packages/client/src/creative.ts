// Creative Studio (ADR-0090): a project goes from a song and an idea to a plan of shots a person can
// change. The analysis tool is an optional component, set up with its size shown first. A project is a
// creation of its own kind.
import { HttpError, type Transport, errorMessage } from "./transport";

export const CREATIVE_PRODUCT_ID = "wasifyai-creative";
export const ANALYSIS_COMPONENT = "music-analysis";

export type CreativeShape = "landscape" | "portrait" | "square";
export type ShotMotion = "Hold" | "Animate" | "Sing";
/** a music video of a song, or a story read aloud (CS5) */
export type CreativeSkill = "song" | "story";
export type ProjectStatus = "draft" | "planning" | "planned" | "failed" | "stopped" | "interrupted";

export type CastMember = {
  name: string;
  look: string;
  photos_only: boolean;
  /** pictures of them from the library, so every shot starts from the same face */
  pictures?: string[];
  /** a saved voice for what they say in a story */
  voice?: string | null;
};
/** An object or place with words that are used again in every picture of it. */
export type FixedWords = { name: string; words: string };

export type Brief = {
  /** "song" when left out */
  skill?: CreativeSkill;
  /** the song; for a story, its reading once it is made */
  track_id: string;
  /** a story's text: the narrator reads it, words in quotes are said by the person named in the sentence */
  story?: string | null;
  /** the saved voice that reads a story */
  narrator?: string | null;
  idea: string;
  style: string;
  cast: CastMember[];
  places: string[];
  fixed?: FixedWords[];
  /** left out, the words the song was made with are used */
  lyrics: string | null;
  shape: CreativeShape;
  /** -2 few long shots, +2 many short ones */
  cut_speed: number;
};

export type Shot = {
  id: string;
  start: number;
  end: number;
  /** the part of the plan it belongs to */
  beat: number;
  shows: string;
  who: string[];
  place: string;
  camera: string;
  line: string;
  note: string;
  motion: ShotMotion;
  /** the model's sentence did not pass the checks, so this is plain words for a person to rewrite */
  fallback: boolean;
};

export type PlanPart = { what: string; who: string; place: string };
export type StoryBible = { title: string; tone: string; ending: string };
export type Plan = { places: string[]; beats: PlanPart[]; shots: Shot[]; bible?: StoryBible };

export type SongSection = { start: number; end: number; energy: number; label: string };
export type SongFacts = {
  seconds?: number;
  bpm?: number;
  beats?: number[];
  downbeats?: number[];
  sections?: SongSection[];
  /** `who` is the person of the cast who says a line of a story; none for the narrator or a song */
  lines?: { text: string; start: number | null; end: number | null; who?: string | null }[];
  lines_timed?: boolean;
  /** the sound is a story read aloud, not a song */
  story?: boolean;
};

export type CreativeProject = {
  id: string;
  title: string;
  status: ProjectStatus;
  brief: Brief;
  facts: SongFacts;
  plan: Plan | null;
  revision: number;
  stage: string;
  progress: number;
  error: string | null;
  elapsed_s: number | null;
  /** the Ask tab's chat, so that coming back finds it */
  conversation_id?: string | null;
  created_at: string;
  updated_at: string;
  /** a plan or a rewrite is running for it now */
  live: boolean;
  shots: ShotsState;
  /** stills, a preview or the video are being made for it now */
  shots_live: boolean;
  /** the Cut step; null while there is no plan. Lists of projects leave it out. */
  cut?: CutState | null;
};

export type StillMode = "plain" | "reference";

/** One still or clip of a shot. Taken from the library, so it can be deleted there. */
export type Take = {
  id: string;
  /** a lipsync take is a sung (or spoken) close up, made from the still with the song's part */
  kind: "image" | "video" | "lipsync";
  item_id: string;
  mode: string;
  seconds: number | null;
  prompt: string;
  created_at: string;
  /** the shot or the brief changed after it was made */
  out_of_date: boolean;
  chosen: boolean;
};

export type ShotsRun = {
  kind: "stills" | "motion" | "preview" | "cut";
  status: "running" | "done" | "stopped" | "failed" | "interrupted";
  stage: string;
  finished: number;
  total: number;
  failed: number;
  error: string | null;
};

export type ProjectPreview = {
  url: string | null;
  seconds: number;
  /** shots that are black, having no still */
  empty_shots: number;
  took_s: number;
  created_at: string;
  /** false once a cut or a chosen take changed after it was joined */
  current: boolean;
};

export type ShotsState = {
  takes: Record<string, Take[]>;
  missing: string[];
  out_of_date: string[];
  run: ShotsRun | null;
  preview: ProjectPreview | null;
};

export type CaptionKind = "line" | "title" | "lower";

/** One piece of the cut's picture track: a shot's chosen version, or something put there by hand. */
export type CutPiece = {
  id: string;
  shot_id: string | null;
  /** the shot's number in the plan, when it is one */
  number: number | null;
  start: number;
  end: number;
  length: number;
  fade: boolean;
  source: { kind: "image" | "video"; item_id: string } | null;
  /** what is shown; null when there is nothing yet, so it is black */
  kind: "image" | "video" | null;
  item_id: string | null;
  camera: string;
};

export type CutCaption = {
  id: string;
  kind: CaptionKind;
  text: string;
  start: number;
  end: number;
};

export type CutVideo = {
  url: string | null;
  shape: CreativeShape;
  seconds: number;
  bytes: number;
  took_s: number;
  created_at: string;
  /** false once the cut changed after it was made */
  current: boolean;
};

export type CutState = {
  items: CutPiece[];
  captions: CutCaption[];
  captions_on: boolean;
  can_undo: boolean;
  can_redo: boolean;
  summary: {
    pictures_end: number;
    song_s: number;
    /** seconds at the end with no picture */
    black_tail: number;
    /** seconds of pictures after the song ends, which are not shown */
    cut_short: number;
    plan_changed: boolean;
    /** pieces with nothing to show yet */
    empty: number;
  };
  render: CutVideo | null;
  /** the videos kept in Your videos, newest first */
  exports: { video_id: string; title: string; created_at: string }[];
};

export type CutEdit =
  | { op: "move"; item_id: string; to: number }
  | { op: "length"; item_id: string; by_beats: number }
  | { op: "split"; item_id: string; at?: number }
  | { op: "fade"; item_id: string; fade: boolean }
  | { op: "remove"; item_id: string }
  | {
      op: "insert";
      after: string | null;
      kind: "image" | "video";
      item_id: string;
      length?: number;
    }
  | { op: "use"; item_id: string; kind?: "image" | "video"; source_id?: string | null }
  | {
      op: "caption";
      caption_id: string;
      text?: string;
      by_beats?: number;
      start?: number;
      end?: number;
    }
  | { op: "add_caption"; kind: CaptionKind; text: string; start: number; end: number }
  | { op: "remove_caption"; caption_id: string }
  | { op: "captions"; on: boolean }
  | { op: "song_lines" }
  | { op: "reset" };

/** The honest panel: what making these will take, before it starts. */
export type StillsEstimate = {
  count: number;
  portraits: number;
  motions: Record<ShotMotion, number>;
  missing: number;
  out_of_date: number;
  seconds_low: number;
  seconds_high: number;
  bytes: number;
  free_bytes: number;
  fit: "fits" | "tight" | "too_big";
  /** the time comes from stills made on this computer, not the general figure */
  measured: boolean;
  ready: boolean;
  /** what to do first when the picture model is not ready */
  step: string | null;
};

/** Motion (ADR-0090 CS4): draft is quick and soft, final is sharp and about four times as long. */
export type MotionQuality = "draft" | "final";

/** The honest panel for clips: which stretch, how many still to make, how long, how much disk. */
export type MotionEstimate = {
  quality: MotionQuality;
  /** clips still to make */
  count: number;
  /** shots in the stretch, or marked Animate */
  shots: number;
  /** of them, shots with no still to start from */
  no_still: number;
  start: number;
  end: number;
  /** the stretch was chosen as the song's loudest part */
  loudest: boolean;
  sections: { start: number; end: number; label: string }[];
  seconds_low: number;
  seconds_high: number;
  bytes: number;
  free_bytes: number;
  fit: "fits" | "tight" | "too_big";
  /** the time comes from clips made on this computer */
  measured: boolean;
  /** of the clips to make, the shots that sing (lip sync) */
  sung?: number;
  ready: boolean;
  /** what to do first when the video model is not ready */
  step: string | null;
};

export type MotionRequest = { quality: MotionQuality; start?: number; shot_id?: string };

export type PlanEdit =
  | {
      op: "set_shot";
      shot_id: string;
      shows?: string;
      motion?: ShotMotion;
      place?: string;
      camera?: string;
      note?: string;
    }
  | { op: "delete_shot"; shot_id: string }
  | { op: "add_shot"; after: string; shows?: string }
  | { op: "move_cut"; shot_id: string; by_beats: number };

/** A thing of the library tagged with this project. The thing itself stays in the library. */
export type ProjectMedia = {
  kind: string;
  item_id: string;
  shot_id: string | null;
  created_at: string;
};

export type PlanLogEntry = { step: string; asked: string; said: string; created_at: string };

/** The analysis tool as the setup card shows it. */
export type AnalysisState =
  | { state: "unsupported"; reason: string }
  | { state: "missing"; bytes: number }
  | { state: "installing"; share: number | null; label: string }
  | { state: "ready" }
  | { state: "failed"; message: string; bytes: number }
  /** a service: the tool is on its workers, set up by an admin, not from this page */
  | { state: "elsewhere"; reason: string };

export type CreativeApi = {
  analysis: () => Promise<AnalysisState>;
  installAnalysis: (bytes: number) => Promise<void>;
  cancelAnalysis: () => Promise<void>;
  list: (limit?: number) => Promise<CreativeProject[]>;
  byIds: (ids: string[]) => Promise<CreativeProject[]>;
  get: (id: string) => Promise<CreativeProject>;
  add: (title: string, brief: Brief) => Promise<CreativeProject>;
  change: (id: string, change: { title?: string; brief?: Brief }) => Promise<CreativeProject>;
  /** `withMade` also deletes from the library what was made for the project */
  remove: (id: string, withMade?: boolean) => Promise<void>;
  plan: (id: string, again?: boolean) => Promise<CreativeProject>;
  stop: (id: string) => Promise<CreativeProject>;
  edit: (id: string, edits: PlanEdit[]) => Promise<CreativeProject>;
  undo: (id: string) => Promise<CreativeProject>;
  rewritePart: (id: string, part: number) => Promise<CreativeProject>;
  log: (id: string) => Promise<PlanLogEntry[]>;
  keepConversation: (id: string, conversationId: string) => Promise<void>;
  media: (id: string) => Promise<ProjectMedia[]>;
  addMedia: (id: string, kind: string, itemId: string, shotId?: string) => Promise<ProjectMedia[]>;
  removeMedia: (id: string, kind: string, itemId: string) => Promise<ProjectMedia[]>;
  characters: () => Promise<CastMember[]>;
  estimateStills: (id: string, mode: StillMode, redo: boolean) => Promise<StillsEstimate>;
  makeStills: (id: string, mode: StillMode, redo: boolean) => Promise<CreativeProject>;
  stopStills: (id: string) => Promise<CreativeProject>;
  redoShot: (id: string, shot: string, mode: StillMode) => Promise<CreativeProject>;
  chooseTake: (id: string, shot: string, take: string) => Promise<CreativeProject>;
  estimateMotion: (id: string, ask: MotionRequest) => Promise<MotionEstimate>;
  /** animate a draft excerpt, the shots marked Animate, or one shot; stop with stopStills */
  makeMotion: (id: string, ask: MotionRequest) => Promise<CreativeProject>;
  preview: (id: string) => Promise<CreativeProject>;
  editCut: (id: string, edits: CutEdit[], note?: string) => Promise<CreativeProject>;
  undoCut: (id: string) => Promise<CreativeProject>;
  redoCut: (id: string) => Promise<CreativeProject>;
  /** make the cut's video to watch; follow it with get */
  makeVideo: (id: string) => Promise<CreativeProject>;
  /** make it if it changed, then keep it in Your videos as a new video; follow it with get */
  keepVideo: (id: string, title?: string) => Promise<CreativeProject>;
};

type ComponentStatus =
  | { state: "unsupported"; reason: string }
  | { state: "not_installed"; needs_bytes: number }
  | {
      state: "installing";
      progress: { label: string; bytes_done: number | null; bytes_total: number | null };
    }
  | { state: "installed" }
  | { state: "failed"; message: string };

export function createCreativeApi(
  transport: Transport,
  { hosted = false }: { hosted?: boolean } = {},
): CreativeApi {
  const base = `/products/${CREATIVE_PRODUCT_ID}/creative/projects`;
  const statusPath = `/products/${CREATIVE_PRODUCT_ID}/creative/status`;
  const component = `/components/${ANALYSIS_COMPONENT}`;
  let lastBytes = 0;

  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }
  const post = <T>(path: string, body: unknown = {}, method = "POST") =>
    json<T>(path, {
      method,
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  const one = (id: string) => `${base}/${encodeURIComponent(id)}`;

  return {
    analysis: async () => {
      if (hosted) {
        const s = await json<{ analysis_ready: boolean; analysis_problem: string | null }>(
          statusPath,
        );
        return s.analysis_ready
          ? { state: "ready" }
          : { state: "elsewhere", reason: s.analysis_problem ?? "Song analysis is not set up yet." };
      }
      const { status } = await json<{ status: ComponentStatus }>(component);
      switch (status.state) {
        case "unsupported":
          return status;
        case "not_installed":
          lastBytes = status.needs_bytes;
          return { state: "missing", bytes: status.needs_bytes };
        case "installing": {
          const { bytes_done: done, bytes_total: total, label } = status.progress;
          return { state: "installing", label, share: done && total ? done / total : null };
        }
        case "installed":
          return { state: "ready" };
        default:
          return { state: "failed", message: status.message, bytes: lastBytes };
      }
    },
    installAnalysis: async (bytes) => {
      if (hosted) throw new Error("This is set up by whoever runs this service, not from this page.");
      await post(`${component}/install`, { confirm_bytes: bytes, repair: false });
    },
    cancelAnalysis: async () => {
      if (!hosted) await post(`${component}/cancel`);
    },
    list: async (limit = 50) =>
      (await json<{ items: CreativeProject[] }>(`${base}?limit=${limit}`)).items,
    byIds: async (ids) =>
      ids.length
        ? (
            await json<{ items: CreativeProject[] }>(
              `${base}?ids=${ids.map(encodeURIComponent).join(",")}`,
            )
          ).items
        : [],
    get: (id) => json<CreativeProject>(one(id)),
    add: (title, brief) => post<CreativeProject>(base, { title, brief }),
    change: (id, change) => post<CreativeProject>(one(id), change, "PATCH"),
    remove: async (id, withMade = false) => {
      const res = await transport.fetch(`${one(id)}${withMade ? "?with_media=true" : ""}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    },
    plan: (id, again = false) => post<CreativeProject>(`${one(id)}/plan`, { again }),
    stop: (id) => post<CreativeProject>(`${one(id)}/plan/stop`),
    edit: (id, edits) => post<CreativeProject>(`${one(id)}/edits`, { edits }),
    undo: (id) => post<CreativeProject>(`${one(id)}/undo`),
    rewritePart: (id, part) => post<CreativeProject>(`${one(id)}/parts/${part}/rewrite`),
    log: async (id) => (await json<{ items: PlanLogEntry[] }>(`${one(id)}/log`)).items,
    keepConversation: async (id, conversationId) => {
      await post(`${one(id)}/conversation`, { conversation_id: conversationId }, "PUT");
    },
    media: async (id) => (await json<{ items: ProjectMedia[] }>(`${one(id)}/media`)).items,
    addMedia: async (id, kind, itemId, shotId) =>
      (
        await post<{ items: ProjectMedia[] }>(`${one(id)}/media`, {
          kind,
          item_id: itemId,
          shot_id: shotId ?? null,
        })
      ).items,
    removeMedia: async (id, kind, itemId) =>
      (
        await json<{ items: ProjectMedia[] }>(
          `${one(id)}/media/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`,
          { method: "DELETE" },
        )
      ).items,
    characters: async () =>
      (await json<{ items: CastMember[] }>(`/products/${CREATIVE_PRODUCT_ID}/creative/characters`))
        .items,
    estimateStills: (id, mode, redo) =>
      json<StillsEstimate>(
        `${one(id)}/shots/estimate?mode=${mode}&redo_out_of_date=${redo ? "true" : "false"}`,
      ),
    makeStills: (id, mode, redo) =>
      post<CreativeProject>(`${one(id)}/shots`, { mode, redo_out_of_date: redo }),
    stopStills: (id) => post<CreativeProject>(`${one(id)}/shots/stop`),
    estimateMotion: (id, ask) => {
      const query = new URLSearchParams({ quality: ask.quality });
      if (ask.start !== undefined) query.set("start", String(ask.start));
      if (ask.shot_id) query.set("shot_id", ask.shot_id);
      return json<MotionEstimate>(`${one(id)}/motion/estimate?${query}`);
    },
    makeMotion: (id, ask) => post<CreativeProject>(`${one(id)}/motion`, ask),
    redoShot: (id, shot, mode) =>
      post<CreativeProject>(`${one(id)}/shots/${encodeURIComponent(shot)}/redo`, { mode }),
    chooseTake: (id, shot, take) =>
      post<CreativeProject>(
        `${one(id)}/shots/${encodeURIComponent(shot)}/chosen`,
        { take_id: take },
        "PUT",
      ),
    preview: (id) => post<CreativeProject>(`${one(id)}/preview`),
    editCut: (id, edits, note) =>
      post<CreativeProject>(`${one(id)}/cut/edits`, note ? { edits, note } : { edits }),
    undoCut: (id) => post<CreativeProject>(`${one(id)}/cut/undo`),
    redoCut: (id) => post<CreativeProject>(`${one(id)}/cut/redo`),
    makeVideo: (id) => post<CreativeProject>(`${one(id)}/cut/video`),
    keepVideo: (id, title) => post<CreativeProject>(`${one(id)}/cut/keep`, { title: title ?? "" }),
  };
}
