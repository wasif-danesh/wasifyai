// Creative Studio (ADR-0090): a project goes from a song and an idea to a plan of shots a person can
// change. The analysis tool is an optional component, set up with its size shown first. A project is a
// creation of its own kind.
import { HttpError, type Transport, errorMessage } from "./transport";

export const CREATIVE_PRODUCT_ID = "wasifyai-creative";
export const ANALYSIS_COMPONENT = "music-analysis";

export type CreativeShape = "landscape" | "portrait" | "square";
export type ShotMotion = "Hold" | "Animate" | "Sing";
export type ProjectStatus = "draft" | "planning" | "planned" | "failed" | "stopped" | "interrupted";

export type CastMember = { name: string; look: string; photos_only: boolean };

export type Brief = {
  track_id: string;
  idea: string;
  style: string;
  cast: CastMember[];
  places: string[];
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
export type Plan = { places: string[]; beats: PlanPart[]; shots: Shot[] };

export type SongSection = { start: number; end: number; energy: number; label: string };
export type SongFacts = {
  seconds?: number;
  bpm?: number;
  beats?: number[];
  downbeats?: number[];
  sections?: SongSection[];
  lines?: { text: string; start: number | null; end: number | null }[];
  lines_timed?: boolean;
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
};

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
  | { state: "failed"; message: string; bytes: number };

export type CreativeApi = {
  analysis: () => Promise<AnalysisState>;
  installAnalysis: (bytes: number) => Promise<void>;
  cancelAnalysis: () => Promise<void>;
  list: (limit?: number) => Promise<CreativeProject[]>;
  byIds: (ids: string[]) => Promise<CreativeProject[]>;
  get: (id: string) => Promise<CreativeProject>;
  add: (title: string, brief: Brief) => Promise<CreativeProject>;
  change: (id: string, change: { title?: string; brief?: Brief }) => Promise<CreativeProject>;
  remove: (id: string) => Promise<void>;
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

export function createCreativeApi(transport: Transport): CreativeApi {
  const base = `/products/${CREATIVE_PRODUCT_ID}/creative/projects`;
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
      await post(`${component}/install`, { confirm_bytes: bytes, repair: false });
    },
    cancelAnalysis: async () => {
      await post(`${component}/cancel`);
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
    remove: async (id) => {
      const res = await transport.fetch(one(id), { method: "DELETE" });
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
  };
}
