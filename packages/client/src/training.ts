// Training (ADR-0073, ADR-0076): a set of pictures, the descriptions the app writes, a run, and the models it
// leaves. The same engine routes serve the desktop window; only the transport differs. A trained model is a
// creation of its own kind, `lora`.
import { HttpError, type Transport, errorMessage } from "./transport";

export const TRAINING_PRODUCT_ID = "wasifyai-training";

export type TrainKind = "character" | "style" | "object";
export type Statement = "mine" | "permission" | "drawing" | "artwork";

export type TrainStatus = {
  ready: boolean;
  problem: string | null;
  /** the trainer is a preview: it runs the steps and learns nothing, and the screens say so */
  preview: boolean;
  engine: Record<string, unknown>;
  fit: { verdict: "fits" | "tight" | "too_big"; reason: string } | null;
  busy: boolean;
  active_run: string | null;
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
  status: "working" | "done" | "failed" | "cancelled";
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
    statement: string;
    evaluation: { passed: boolean | null; note: string };
    trained_at: string;
  };
  created_at: string;
};

export type TrainingApi = {
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
    cancelRun: (id) =>
      json<{ cancelled: boolean }>(`${base}/runs/${enc(id)}/cancel`, { method: "POST" }),
    sampleUrl: (runId, name) => objectUrl(`${base}/runs/${enc(runId)}/samples/${enc(name)}`),
    models: async () => (await json<{ models: TrainedModel[] }>(`${base}/models`)).models,
    model: (id) => json<TrainedModel>(`${base}/models/${enc(id)}`),
    renameModel: (id, name) =>
      json<TrainedModel>(`${base}/models/${enc(id)}`, send("PATCH", { name })),
    removeModel: (id) => del(`${base}/models/${enc(id)}`),
  };
}
