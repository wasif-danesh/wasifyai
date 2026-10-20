// Video Builder (ADR-0077): the render component (set up on request, with the size shown first) and
// the projects a person writes and makes videos from. The same engine routes serve the desktop window;
// only the transport differs. A finished render is a clip of Your videos (`videos.ts`).
import { HttpError, type Transport, errorMessage } from "./transport";

export const VIDEO_BUILDER_PRODUCT_ID = "wasifyai-video";

export type ComponentPart = {
  name: string;
  version: string;
  bytes: number;
  licence: string;
  source: string;
};

export type ComponentProgress = {
  state: "idle" | "installing" | "ready" | "failed";
  step: string | null;
  message: string;
  done_bytes: number;
  total_bytes: number;
};

/** What the setup card shows: is it there, what would it fetch, how far has it got. */
export type BuilderComponent = {
  installed: boolean;
  source: string | null;
  plan: {
    supported: boolean;
    platform: string;
    bytes: number;
    parts: ComponentPart[];
    found: { path: string } | null;
  };
  progress: ComponentProgress;
  sandbox: { network: string; telemetry: string };
};

export type BuilderShape = "landscape" | "portrait" | "square";
export type BuilderTheme = "midnight" | "sunrise" | "forest" | "paper";
export type BuilderFormat = "mp4" | "webm" | "mov";

/** One thing the person fills in; the window builds its form from these. */
export type FieldKind = "text" | "longtext" | "lines" | "rows" | "choice" | "seconds";
export type FieldInfo = {
  id: string;
  kind: FieldKind;
  label: string;
  required: boolean;
  /** text and longtext: the most characters; lines and rows: the most in one line */
  max_chars: number;
  /** seconds: the shortest; lines and rows: the fewest lines */
  min: number;
  /** seconds: the longest; lines and rows: the most lines */
  max: number;
  default: string | number | null;
  choices: { id: string; label: string }[];
  hint: string;
};

export type TemplateInfo = {
  id: string;
  title: string;
  description: string;
  fields: FieldInfo[];
  /** an overlay with no background: made as webm or mov to lay over other video */
  transparent: boolean;
  formats: BuilderFormat[];
};

export type TemplateCatalogue = {
  templates: TemplateInfo[];
  shapes: Record<BuilderShape, { width: number; height: number }>;
  themes: Record<BuilderTheme, { from: string; to: string; ink: string; accent: string }>;
  fonts: Record<string, string>;
};

/** What a project holds: the typed words by field id (rows and lines as the text typed). */
export type BuilderSlots = Record<
  string,
  string | number | { label: string; value: string }[] | string[]
>;

/** What was found when the words on the screen were compared with the words that were typed. */
export type BuilderCheck = {
  ok: boolean;
  checked: number;
  problems: { slot: string; code: string; message: string }[];
  message: string;
};

export type RenderStatus = "working" | "done" | "failed" | "cancelled";

export type BuilderRender = {
  id: string;
  composition_id: string;
  status: RenderStatus;
  /** 0 to 1 while it works */
  progress: number;
  /** while it works: "checking" the words, then "drawing" the video */
  stage: "checking" | "drawing" | null;
  format: BuilderFormat;
  /** what the check of the words found; null when the render ended before it ran */
  check: BuilderCheck | null;
  /** plain text for the person, when it failed or was stopped */
  error: string | null;
  video_id: string | null;
  video_url: string | null;
  poster_url: string | null;
  elapsed_s: number | null;
  peak_mb: number | null;
  /** how many requests the video made that were refused (nothing leaves the computer) */
  blocked: number;
  started_at: string;
  finished_at: string | null;
};

export type BuilderProject = {
  id: string;
  title: string;
  template: string;
  slots: BuilderSlots;
  created_at: string;
  updated_at: string;
  renders: BuilderRender[];
  /** the file kinds this template can be made as */
  formats: BuilderFormat[];
  /** three moments (seconds) to show as stills: coming in, half way, everything on screen */
  preview_times: number[];
  /** whether Undo has an earlier version to bring back */
  can_undo: boolean;
  /** the page the template makes of the words: the read-only code view (only when one project is opened) */
  code?: string;
};

export type BuilderStatus = {
  ready: boolean;
  fit: { verdict: "fits" | "tight" | "too_big"; reason: string };
  busy: boolean;
};

export type LintFinding = { file: string; line: number; code: string; message: string };

export type VideoBuilderApi = {
  component(): Promise<BuilderComponent>;
  /** Set it up after the person has seen `bytes`: the engine refuses a different number. */
  install(confirmBytes: number): Promise<BuilderComponent>;
  uninstall(): Promise<{ freed_bytes: number } & BuilderComponent>;
  status(): Promise<BuilderStatus>;
  templates(): Promise<TemplateCatalogue>;
  list(): Promise<BuilderProject[]>;
  get(id: string): Promise<BuilderProject>;
  create(template: string, slots: BuilderSlots): Promise<BuilderProject>;
  update(id: string, slots: BuilderSlots): Promise<BuilderProject>;
  /** Bring back the words as they were before the last change. */
  undo(id: string): Promise<BuilderProject>;
  /** Check the words on the screen against the typed words, without making the video. */
  check(id: string): Promise<BuilderCheck>;
  remove(id: string): Promise<void>;
  lint(id: string): Promise<{ ok: boolean; findings: LintFinding[] }>;
  /** A still of the project at `at` seconds (the middle moment when left out), as an object URL. */
  preview(id: string, at?: number): Promise<string>;
  render(id: string, format?: BuilderFormat): Promise<BuilderRender>;
  renderStatus(renderId: string): Promise<BuilderRender>;
  cancel(renderId: string): Promise<BuilderRender>;
};

export function createVideoBuilderApi(
  transport: Transport,
  product = VIDEO_BUILDER_PRODUCT_ID,
): VideoBuilderApi {
  const base = `/products/${product}/builder`;

  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }

  const send = (method: string, body?: unknown): RequestInit => ({
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const enc = encodeURIComponent;

  return {
    component: () => json<BuilderComponent>("/desktop/video-builder"),
    install: (confirmBytes) =>
      json<BuilderComponent>(
        "/desktop/video-builder/install",
        send("POST", { confirm_bytes: confirmBytes }),
      ),
    uninstall: () => json("/desktop/video-builder/uninstall", { method: "POST" }),
    status: () => json<BuilderStatus>(`${base}/status`),
    templates: () => json<TemplateCatalogue>(`${base}/templates`),
    list: async () => (await json<{ items: BuilderProject[] }>(`${base}/projects`)).items,
    get: (id) => json<BuilderProject>(`${base}/projects/${enc(id)}`),
    create: (template, slots) =>
      json<BuilderProject>(`${base}/projects`, send("POST", { template, slots })),
    update: (id, slots) =>
      json<BuilderProject>(`${base}/projects/${enc(id)}`, send("PATCH", { slots })),
    undo: (id) => json<BuilderProject>(`${base}/projects/${enc(id)}/undo`, { method: "POST" }),
    check: (id) => json<BuilderCheck>(`${base}/projects/${enc(id)}/check`, { method: "POST" }),
    async remove(id) {
      const res = await transport.fetch(`${base}/projects/${enc(id)}`, { method: "DELETE" });
      if (!res.ok && res.status !== 404) throw new HttpError(res.status, await errorMessage(res));
    },
    lint: (id) =>
      json<{ ok: boolean; findings: LintFinding[] }>(`${base}/projects/${enc(id)}/lint`, {
        method: "POST",
      }),
    async preview(id, at) {
      const query = at === undefined ? "" : `?at=${at}`;
      const res = await transport.fetch(`${base}/projects/${enc(id)}/preview${query}`);
      if (res.status === 401) transport.onUnauthorized?.();
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
      return URL.createObjectURL(await res.blob());
    },
    render: (id, format) =>
      json<BuilderRender>(
        `${base}/projects/${enc(id)}/render`,
        format ? send("POST", { format }) : { method: "POST" },
      ),
    renderStatus: (rid) => json<BuilderRender>(`${base}/renders/${enc(rid)}`),
    cancel: (rid) => json<BuilderRender>(`${base}/renders/${enc(rid)}/cancel`, { method: "POST" }),
  };
}

/** "288 MB" for a download size. */
export function megabytes(bytes: number): string {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`;
}
