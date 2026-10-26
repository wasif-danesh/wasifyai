// Training (ADR-0073, ADR-0076): a set of pictures, the descriptions the app writes, a run, and the models it
// leaves. The same engine routes serve the desktop window; only the transport differs. A trained model is a
// creation of its own kind, `lora`.
import { HttpError, type Transport, errorMessage } from "./transport";

export const TRAINING_PRODUCT_ID = "wasifyai-training";

export type TrainKind = "character" | "style" | "object";

/** What a trained model is: pictures of one of the three kinds, or how a person writes. */
export type TrainedKind = TrainKind | "writing";
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

export type TrainMethodId = "lora" | "qlora" | "full";

/** One way of teaching a model, in words first; `can` false carries the reason. */
export type TrainMethod = {
  id: TrainMethodId;
  title: string;
  technical: string;
  /** Advanced only: the screen shows it under "For experts" */
  advanced: boolean;
  can: boolean;
  reason: string;
};

/** A model that may be taught, or one on this computer that cannot be (with the reason). */
export type TrainBase = {
  /** what this model is good for, and what a real run on this Mac measured (writing models) */
  note?: string;
  measured?: string;
  /** empty for a model with no descriptor: it is listed, not offered */
  id: string;
  title: string;
  licence: string;
  engine: string;
  recommended: boolean;
  can_teach: boolean;
  reason: string;
  installed: boolean;
  methods: TrainMethod[];
};

export type TrainChoices = {
  family: string;
  default_base: string;
  default_method: TrainMethodId;
  bases: TrainBase[];
};

/** The person's choice: leave a field out for the recommendation. */
export type TrainChoice = { base?: string; method?: TrainMethodId };

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
  /** what teaching this set would take, by its own size: the steps and "About 40 minutes" */
  steps?: number;
  estimate?: string;
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

/** One question put to the model before it was taught and after, side by side. */
export type WritingAnswer = { question: string; before: string; after: string };

export type WritingQuality = "quick" | "better";
export type WritingRights = "mine" | "permission";

export type WritingExample = { ask: string; answer: string };

export type WritingCheck = { level: "ok" | "warn" | "error"; code: string; message: string };

/** What a run of a set would take, and what stops it, in words. */
export type WritingPlan = {
  examples: number;
  dropped: string[];
  checks: WritingCheck[];
  steps: number;
  estimate: string;
  base: string;
  base_title: string;
  /** what this model is good for, one sentence */
  base_note: string;
  held_back: number;
  missing: string | null;
};

export type WritingSet = {
  id: string;
  name: string;
  quality: WritingQuality;
  base: string;
  rights: WritingRights | "";
  created_at: string;
  examples: number;
  missing: string | null;
  steps: number;
  estimate: string;
  /** with the whole set */
  rows?: WritingExample[];
  plan?: WritingPlan;
};

/** One thing the writing trainer can fetch for a base: its weights ("model") or the chat form of it ("chat"). */
export type LanguagePart = {
  have: boolean;
  bytes: number;
  title: string;
  needs_free_bytes: number;
  progress: {
    state: "idle" | "installing" | "ready" | "failed";
    message: string;
    done_bytes: number;
    total_bytes: number;
  };
};

/** A base a writing model can be taught on, and what of it is on this computer. */
export type LanguageBase = {
  id: string;
  title: string;
  licence: string;
  source: string;
  /** set up with the trainer, not fetched on its own */
  main: boolean;
  problem: string | null;
  model: LanguagePart;
  chat: LanguagePart;
};

export type WritingStatus = {
  ready: boolean;
  problem: string | null;
  engine: Record<string, unknown>;
  fit: { verdict: "fits" | "tight" | "too_big"; reason: string } | null;
  busy: boolean;
  active_run: string | null;
  place: "device" | "service";
  min_examples: number;
  good_examples: number;
  rights: WritingRights[];
  qualities: WritingQuality[];
  choices: TrainChoices;
  /** the taught model chat answers with now, if any */
  in_chat: string | null;
  bases: LanguageBase[];
};

export type WritingAsk = { question: string; original: string; mine: string };

export type TrainedModel = {
  id: string;
  run_id: string;
  dataset_id: string | null;
  name: string;
  trigger_word: string;
  kind: TrainedKind;
  base: string;
  preview: boolean;
  adapter_bytes: number | null;
  card: {
    base_title: string;
    licence: string;
    engine: string;
    preview: boolean;
    note: string;
    dataset: {
      name: string;
      kind: TrainedKind;
      pictures?: number;
      examples?: number;
      hash: string;
    };
    /** a language model: the same questions asked before and after, and the loss on answers kept back */
    answers?: WritingAnswer[];
    loss?: {
      first_held_back: number | null;
      last_held_back: number | null;
      last_train: number | null;
    };
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
  /** The writing trainer's component (ADR-0074), set up the same way. */
  writingSetup(): Promise<TrainingSetupState>;
  installWritingSetup(confirmBytes: number): Promise<TrainingSetupState>;
  cancelWritingSetup(): Promise<TrainingSetupState>;
  removeWritingSetup(): Promise<{ freed_bytes: number } & TrainingSetupState>;
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
  startRun(datasetId: string, choice?: TrainChoice): Promise<TrainRun>;
  /** The models and methods that can be chosen for a kind of teaching. */
  choices(kind: TrainKind): Promise<TrainChoices>;
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
  /** "Teach it from examples" (ADR-0074): sets of examples, a run, the side-by-side answers. */
  writingStatus(): Promise<WritingStatus>;
  writingSets(): Promise<WritingSet[]>;
  createWritingSet(name?: string): Promise<WritingSet>;
  writingSet(id: string): Promise<WritingSet>;
  updateWritingSet(
    id: string,
    patch: { name?: string; quality?: WritingQuality; base?: string; rights?: WritingRights },
  ): Promise<WritingSet>;
  /** Replace the examples of a set with these rows. */
  setExamples(id: string, rows: WritingExample[]): Promise<WritingSet>;
  removeWritingSet(id: string): Promise<void>;
  startWritingRun(setId: string): Promise<TrainRun>;
  /** The same question to the original model and to the one taught. */
  askWriting(modelId: string, question: string): Promise<WritingAsk>;
  /** Chat with a taught writing model: the chat engine serves its base with the adapter on top. */
  useWritingInChat(modelId: string): Promise<void>;
  /** Back to the model chat used before. */
  stopWritingInChat(): Promise<{ ended: boolean }>;
  /** What is on this computer for each base a writing model can be taught on. */
  languageBases(): Promise<LanguageBase[]>;
  /** Get the weights of a base, or the chat form of it, after its size was shown. */
  installLanguagePart(
    baseId: string,
    part: "model" | "chat",
    confirmBytes: number,
  ): Promise<LanguageBase[]>;
  cancelLanguagePart(baseId: string, part: "model" | "chat"): Promise<LanguageBase[]>;
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
    startRun: (datasetId, choice) =>
      json<TrainRun>(`${base}/runs`, send("POST", { dataset_id: datasetId, ...choice })),
    choices: (kind) => json<TrainChoices>(`${base}/choices?kind=${enc(kind)}`),
    writingStatus: () => json<WritingStatus>(`${base}/writing/status`),
    writingSets: async () => (await json<{ sets: WritingSet[] }>(`${base}/writing/sets`)).sets,
    createWritingSet: (name = "") =>
      json<WritingSet>(`${base}/writing/sets`, send("POST", { name })),
    writingSet: (id) => json<WritingSet>(`${base}/writing/sets/${enc(id)}`),
    updateWritingSet: (id, patch) =>
      json<WritingSet>(`${base}/writing/sets/${enc(id)}`, send("PATCH", patch)),
    setExamples: (id, rows) =>
      json<WritingSet>(`${base}/writing/sets/${enc(id)}/examples`, send("PUT", { rows })),
    removeWritingSet: async (id) => {
      const res = await transport.fetch(`${base}/writing/sets/${enc(id)}`, { method: "DELETE" });
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    },
    startWritingRun: (setId) =>
      json<TrainRun>(`${base}/writing/sets/${enc(setId)}/runs`, { method: "POST" }),
    useWritingInChat: async (modelId) => {
      await json<unknown>(`${base}/writing/models/${enc(modelId)}/use`, { method: "POST" });
    },
    stopWritingInChat: () => json<{ ended: boolean }>(`${base}/writing/use`, { method: "DELETE" }),
    languageBases: async () =>
      (await json<{ bases: LanguageBase[] }>("/desktop/language-setup/bases")).bases,
    installLanguagePart: async (baseId, part, confirmBytes) =>
      (
        await json<{ bases: LanguageBase[] }>(
          `/desktop/language-setup/bases/${enc(baseId)}/${part}/install`,
          send("POST", { confirm_bytes: confirmBytes }),
        )
      ).bases,
    cancelLanguagePart: async (baseId, part) =>
      (
        await json<{ bases: LanguageBase[] }>(
          `/desktop/language-setup/bases/${enc(baseId)}/${part}/cancel`,
          { method: "POST" },
        )
      ).bases,
    askWriting: (modelId, question) =>
      json<WritingAsk>(`${base}/writing/models/${enc(modelId)}/ask`, send("POST", { question })),
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
    writingSetup: () => json<TrainingSetupState>("/desktop/language-setup"),
    installWritingSetup: (confirmBytes) =>
      json<TrainingSetupState>(
        "/desktop/language-setup/install",
        send("POST", { confirm_bytes: confirmBytes }),
      ),
    cancelWritingSetup: () =>
      json<TrainingSetupState>("/desktop/language-setup/install/cancel", { method: "POST" }),
    removeWritingSetup: () =>
      json<{ freed_bytes: number } & TrainingSetupState>("/desktop/language-setup/uninstall", {
        method: "POST",
      }),
    removeSetup: () =>
      json<{ freed_bytes: number } & TrainingSetupState>("/desktop/training-setup/uninstall", {
        method: "POST",
      }),
  };
}
