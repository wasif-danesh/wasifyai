// Training (ADR-0073, ADR-0076): a set of pictures, the descriptions the app writes, a run, and the models it
// leaves. The same engine routes serve the desktop window; only the transport differs. A trained model is a
// creation of its own kind, `lora`.
import { HttpError, type Transport, errorMessage } from "./transport";

export const TRAINING_PRODUCT_ID = "wasifyai-training";

export type TrainKind = "character" | "style" | "object";
export type Statement = "mine" | "permission" | "drawing" | "artwork";

export type TrainPreflight = {
  ok: boolean;
  /** why it cannot start now, in words (not enough disk, a flat battery) */
  blockers: string[];
  warnings: string[];
  /** what waits while it runs */
  pauses: string;
};

export type TrainStatus = {
  ready: boolean;
  problem: string | null;
  /** the trainer is a preview: it runs the steps and learns nothing, and the screens say so */
  preview: boolean;
  engine: Record<string, unknown>;
  fit: { verdict: "fits" | "tight" | "too_big"; reason: string } | null;
  busy: boolean;
  active_run: string | null;
  /** What to know before a run starts: whether anything stops it, what to look out for (desktop). */
  preflight?: TrainPreflight | null;
  place: "device" | "service";
  min_pictures: number;
  max_pictures: number;
  kinds: TrainKind[];
  /** the words of each statement of rights, by its key */
  statements: Record<Statement, string>;
  base: string;
  steps: Record<TrainKind, number>;
  /** "About 25 minutes", by kind */
  estimates: Record<TrainKind, string>;
};

export type TrainPictureCheck = { code: string; level: "ok" | "warn"; message: string };

export type CaptionState = "none" | "writing" | "done" | "edited" | "failed";

export type TrainPicture = {
  id: string;
  dataset_id: string;
  name: string;
  width: number;
  height: number;
  checks: TrainPictureCheck[];
  caption: string;
  caption_state: CaptionState;
  caption_error: string | null;
  /** a check found a problem: the screen suggests removing it */
  suggest_remove: boolean;
  created_at: string;
};

export type TrainDataset = {
  id: string;
  kind: TrainKind;
  name: string;
  trigger_word: string;
  rights: Statement | "";
  created_at: string;
  pictures: number;
  /** what is missing before a run, in the sentence to show; null when nothing is */
  missing: string | null;
  /** the descriptions are being written */
  writing: boolean;
  /** with the whole set: its pictures and three magic words */
  items?: TrainPicture[];
  suggestions?: string[];
};

export type TrainRun = {
  id: string;
  dataset_id: string;
  status: "working" | "paused" | "done" | "failed" | "cancelled";
  stage: string;
  step: number;
  steps: number;
  progress: number;
  error: string | null;
  base: string;
  /** the names of the sample pictures made so far */
  samples: string[];
  preview: boolean;
  model_id: string | null;
  elapsed_s: number | null;
  estimate: string;
  live: boolean;
  created_at: string;
  finished_at: string | null;
};

/** One picture of the check: what was drawn, and whether it looked like the pictures it learnt from. */
export type CheckedPicture = {
  id: string;
  condition: "with_word" | "without_word" | "without_model";
  prompt: string;
  /** null: it could not be judged (no picture-reading model) */
  same: boolean | null;
  reason: string;
};

/** What "did it learn?" found, in words and a mark (ADR-0073 decision 10). `passed` null: not checked or not judged. */
export type TrainEvaluation = {
  passed: boolean | null;
  note: string;
  at?: string;
  /** [pictures that looked the same, pictures judged], by kind of picture */
  counts?: Partial<Record<CheckedPicture["condition"], [number, number]>>;
  items?: CheckedPicture[];
};

/** A picture to draw for the check; `with_model` says whether the trained model is applied to it. */
export type CheckStep = {
  id: string;
  scene: number;
  condition: CheckedPicture["condition"];
  prompt: string;
  with_model: boolean;
};

export type TrainedModel = {
  id: string;
  run_id: string;
  dataset_id: string | null;
  name: string;
  trigger_word: string;
  kind: TrainKind;
  base: string;
  preview: boolean;
  adapter_bytes: number | null;
  card: {
    base_title: string;
    licence: string;
    engine: string;
    preview: boolean;
    note: string;
    dataset: { name: string; kind: TrainKind; pictures: number; hash: string };
    steps: number;
    seconds: number;
    trigger_word: string;
    /** The name the image engine gives it as a style, once it is published there (else null). */
    published?: { lora_name: string } | null;
    statement: string;
    evaluation: TrainEvaluation;
    trained_at: string;
  };
  created_at: string;
};

/** One thing the setup fetches: what it is, how large, and whose licence it carries. */
export type TrainingSetupPart = {
  name: string;
  version: string;
  bytes: number;
  /** already on this computer: it is not fetched again */
  have: boolean;
  licence: string;
  source: string;
};

/** The trainer's component on a desktop engine: what is there, what it would take, how an install goes. */
export type TrainingSetupState = {
  installed: boolean;
  /** where the trainer is from: "managed" (this app's own), "env", "dev"; null when it is not there */
  tool: string | null;
  base: string | null;
  problem: string | null;
  plan: {
    supported: boolean;
    bytes: number;
    needs_free_bytes: number;
    parts: TrainingSetupPart[];
  };
  progress: {
    state: "idle" | "installing" | "ready" | "failed";
    step: string | null;
    steps: string[];
    message: string;
    done_bytes: number;
    total_bytes: number;
  };
};

export type TrainingApi = {
  /** The pictures to draw to find out whether a model learnt, and how many references it keeps. */
  checkPlan(modelId: string): Promise<{ items: CheckStep[]; refs: number }>;
  /** One picture it drew: does it look like the ones it learnt from? */
  judge(modelId: string, picture: Blob): Promise<{ same: boolean; reason: string }>;
  /** Keep what the check found on the model's card. */
  saveEvaluation(modelId: string, items: CheckedPicture[]): Promise<TrainedModel>;
  /** The trainer's component (desktop only: the web's trainer lives on a worker). */
  setup(): Promise<TrainingSetupState>;
  /** Set it up; `confirmBytes` is the size the person was shown. */
  installSetup(confirmBytes: number): Promise<TrainingSetupState>;
  cancelSetup(): Promise<TrainingSetupState>;
  removeSetup(): Promise<{ freed_bytes: number } & TrainingSetupState>;
  status(): Promise<TrainStatus>;
  datasets(): Promise<TrainDataset[]>;
  createDataset(kind: TrainKind, name?: string): Promise<TrainDataset>;
  dataset(id: string): Promise<TrainDataset>;
  updateDataset(
    id: string,
    change: Partial<Pick<TrainDataset, "kind" | "name" | "trigger_word" | "rights">>,
  ): Promise<TrainDataset>;
  removeDataset(id: string): Promise<void>;
  addPicture(datasetId: string, picture: Blob, name?: string): Promise<TrainPicture>;
  removePicture(datasetId: string, pictureId: string): Promise<void>;
  editCaption(datasetId: string, pictureId: string, caption: string): Promise<TrainPicture>;
  /** Start writing the descriptions: of every picture without one, or (`again`) of all or some. */
  writeCaptions(
    datasetId: string,
    options?: { again?: boolean; pictureIds?: string[] },
  ): Promise<{ writing: number }>;
  /** A picture of the set (`thumb` or `picture`) as an object URL. */
  pictureUrl(datasetId: string, pictureId: string, which: "thumb" | "picture"): Promise<string>;
  startRun(datasetId: string): Promise<TrainRun>;
  runs(): Promise<TrainRun[]>;
  run(id: string): Promise<TrainRun>;
  /** Stop for now and keep the last checkpoint; `resumeRun` picks it up where it stopped. */
  pauseRun(id: string): Promise<{ paused: boolean }>;
  resumeRun(id: string): Promise<TrainRun>;
  /** Stop a run that is going, or discard one that is paused. */
  cancelRun(id: string): Promise<{ cancelled: boolean }>;
  /** A sample picture of a run as an object URL. */
  sampleUrl(runId: string, name: string): Promise<string>;
  models(): Promise<TrainedModel[]>;
  model(id: string): Promise<TrainedModel>;
  renameModel(id: string, name: string): Promise<TrainedModel>;
  removeModel(id: string): Promise<void>;
};

export function createTrainingApi(
  transport: Transport,
  product: string = TRAINING_PRODUCT_ID,
): TrainingApi {
  const base = `/products/${product}/train`;
  const enc = encodeURIComponent;

  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }

  async function objectUrl(path: string): Promise<string> {
    const res = await transport.fetch(path);
    if (res.status === 401) transport.onUnauthorized?.();
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return URL.createObjectURL(await res.blob());
  }

  const send = (method: string, body?: unknown): RequestInit => ({
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const del = async (path: string) => {
    const res = await transport.fetch(path, { method: "DELETE" });
    if (!res.ok && res.status !== 404) throw new HttpError(res.status, await errorMessage(res));
  };

  return {
    status: () => json<TrainStatus>(`${base}/status`),
    datasets: async () => (await json<{ datasets: TrainDataset[] }>(`${base}/datasets`)).datasets,
    createDataset: (kind, name = "") =>
      json<TrainDataset>(`${base}/datasets`, send("POST", { kind, name })),
    dataset: (id) => json<TrainDataset>(`${base}/datasets/${enc(id)}`),
    updateDataset: (id, change) =>
      json<TrainDataset>(`${base}/datasets/${enc(id)}`, send("PATCH", change)),
    removeDataset: (id) => del(`${base}/datasets/${enc(id)}`),
    addPicture: (datasetId, picture, name = "") =>
      json<TrainPicture>(`${base}/datasets/${enc(datasetId)}/items?name=${enc(name)}`, {
        method: "POST",
        headers: { "content-type": picture.type || "application/octet-stream" },
        body: picture,
      }),
    removePicture: (datasetId, pictureId) =>
      del(`${base}/datasets/${enc(datasetId)}/items/${enc(pictureId)}`),
    editCaption: (datasetId, pictureId, caption) =>
      json<TrainPicture>(
        `${base}/datasets/${enc(datasetId)}/items/${enc(pictureId)}`,
        send("PATCH", { caption }),
      ),
    writeCaptions: (datasetId, options = {}) =>
      json<{ writing: number }>(
        `${base}/datasets/${enc(datasetId)}/captions`,
        send("POST", { again: options.again ?? false, item_ids: options.pictureIds ?? null }),
      ),
    pictureUrl: (datasetId, pictureId, which) =>
      objectUrl(`${base}/datasets/${enc(datasetId)}/items/${enc(pictureId)}/${which}`),
    startRun: (datasetId) =>
      json<TrainRun>(`${base}/runs`, send("POST", { dataset_id: datasetId })),
    runs: async () => (await json<{ runs: TrainRun[] }>(`${base}/runs`)).runs,
    run: (id) => json<TrainRun>(`${base}/runs/${enc(id)}`),
    pauseRun: (id) =>
      json<{ paused: boolean }>(`${base}/runs/${enc(id)}/pause`, { method: "POST" }),
    resumeRun: (id) => json<TrainRun>(`${base}/runs/${enc(id)}/resume`, { method: "POST" }),
    cancelRun: (id) =>
      json<{ cancelled: boolean }>(`${base}/runs/${enc(id)}/cancel`, { method: "POST" }),
    sampleUrl: (runId, name) => objectUrl(`${base}/runs/${enc(runId)}/samples/${enc(name)}`),
    models: async () => (await json<{ models: TrainedModel[] }>(`${base}/models`)).models,
    model: (id) => json<TrainedModel>(`${base}/models/${enc(id)}`),
    renameModel: (id, name) =>
      json<TrainedModel>(`${base}/models/${enc(id)}`, send("PATCH", { name })),
    removeModel: (id) => del(`${base}/models/${enc(id)}`),
    checkPlan: (modelId) =>
      json<{ items: CheckStep[]; refs: number }>(`${base}/models/${enc(modelId)}/check`),
    judge: (modelId, picture) =>
      json<{ same: boolean; reason: string }>(`${base}/models/${enc(modelId)}/judge`, {
        method: "POST",
        headers: { "content-type": picture.type || "application/octet-stream" },
        body: picture,
      }),
    saveEvaluation: (modelId, items) =>
      json<TrainedModel>(`${base}/models/${enc(modelId)}/evaluation`, send("PUT", { items })),
    setup: () => json<TrainingSetupState>("/desktop/training-setup"),
    installSetup: (confirmBytes) =>
      json<TrainingSetupState>(
        "/desktop/training-setup/install",
        send("POST", { confirm_bytes: confirmBytes }),
      ),
    cancelSetup: () =>
      json<TrainingSetupState>("/desktop/training-setup/install/cancel", { method: "POST" }),
    removeSetup: () =>
      json<{ freed_bytes: number } & TrainingSetupState>("/desktop/training-setup/uninstall", {
        method: "POST",
      }),
  };
}
