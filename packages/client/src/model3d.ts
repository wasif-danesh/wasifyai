// 3D models (ADR-0080): the component (set up on request, with the size shown first), the picture a
// model is made from and its checks, and the models themselves. The same engine routes serve the
// desktop window; only the transport differs. A finished model is a creation of its own kind.
import { HttpError, type Transport, errorMessage } from "./transport";

export const MODEL3D_PRODUCT_ID = "wasifyai-model3d";

export type Model3dPart = {
  name: string;
  version: string;
  bytes: number;
  licence: string;
  source: string;
};

export type Model3dProgress = {
  state: "idle" | "installing" | "ready" | "failed";
  step: string | null;
  message: string;
  done_bytes: number;
  total_bytes: number;
};

export type Fit = { verdict: "fits" | "tight" | "too_big"; reason: string };

/** What the setup card shows: is it there, what would it fetch, how far has it got. */
export type Model3dComponent = {
  installed: boolean;
  source: string | null;
  plan: {
    supported: boolean;
    platform: string;
    bytes: number;
    parts: Model3dPart[];
    found: { path: string } | null;
  };
  progress: Model3dProgress;
  fit: Fit | null;
  about: { built_with: string; licence: string; where: string };
};

export type Model3dStatus = {
  ready: boolean;
  /** where the work is done: on this computer, or on a service's worker */
  place?: "device" | "service";
  problem: string | null;
  fit: Fit | null;
  busy: boolean;
  active: { kind: "input" | "model"; id: string } | null;
  details: Detail[];
};

export type Detail = "light" | "standard" | "detailed";

export type PictureCheck = { code: string; level: "ok" | "warn" | "stop"; message: string };

/** A picture on its way to becoming a model: cut out, then looked at. */
export type PictureInput = {
  id: string;
  status: "checking" | "ready" | "failed";
  name: string;
  width: number;
  height: number;
  /** what the cut-out is doing now, in words */
  stage: string;
  checks: PictureCheck[];
  error: string | null;
  /** ready, and nothing that stops it */
  can_go_on: boolean;
  created_at: string;
};

export type ModelStatus = "working" | "done" | "failed" | "cancelled";

export type Model3d = {
  id: string;
  title: string;
  prompt: string;
  input_id: string | null;
  status: ModelStatus;
  /** the stage in words while it works */
  stage: string;
  /** 0 to 1 */
  progress: number;
  error: string | null;
  detail: Detail;
  seed: number;
  recipe: Record<string, unknown>;
  elapsed_s: number | null;
  peak_gb: number | null;
  glb_bytes: number | null;
  created_at: string;
  finished_at: string | null;
  /** it is the one running now */
  live: boolean;
};

export type MakeRequest = {
  input_id: string;
  title?: string;
  prompt?: string;
  detail?: Detail;
  seed?: number;
  /** the person says they may use the picture, and it is not a photo of a real person who has not agreed */
  rights: boolean;
};

export type Model3dApi = {
  component(): Promise<Model3dComponent>;
  /** Set it up after the person has seen `bytes`: the engine refuses a different number. */
  install(confirmBytes: number): Promise<Model3dComponent>;
  cancelInstall(): Promise<Model3dComponent>;
  uninstall(): Promise<{ freed_bytes: number } & Model3dComponent>;
  status(): Promise<Model3dStatus>;
  /** Add a picture (PNG, JPEG or WebP). It is cut out and looked at in the background. */
  addPicture(picture: Blob, name?: string): Promise<PictureInput>;
  picture(id: string): Promise<PictureInput>;
  /** The picture or its cut-out as an object URL. */
  pictureImage(id: string, which: "picture" | "cutout"): Promise<string>;
  removePicture(id: string): Promise<void>;
  make(request: MakeRequest): Promise<Model3d>;
  list(): Promise<Model3d[]>;
  get(id: string): Promise<Model3d>;
  cancel(id: string): Promise<Model3d & { stopped: boolean }>;
  again(id: string): Promise<Model3d>;
  rename(id: string, title: string): Promise<Model3d>;
  remove(id: string): Promise<void>;
  /** The model's GLB, a thumbnail, or the picture it came from, as an object URL. */
  fileUrl(id: string, which: "file" | "thumb" | "source" | "cutout"): Promise<string>;
  exportCopy(id: string, path?: string): Promise<{ name: string; path: string }>;
};

export type Model3dApiOptions = {
  product?: string;
  /** The web: the component is on a worker, set up by whoever runs the service, so there is nothing to
   * install from the page and its state is read from the product's status. */
  hosted?: boolean;
};

const HOSTED_ABOUT = {
  built_with: "Built with DINOv3",
  licence: "Models: MIT, and the DINOv3 licence for the image encoder.",
  where: "Made on the service's graphics card; the picture is deleted when the model is made.",
};

export function createModel3dApi(
  transport: Transport,
  options: Model3dApiOptions | string = {},
): Model3dApi {
  const { product = MODEL3D_PRODUCT_ID, hosted = false } =
    typeof options === "string" ? { product: options } : options;
  const base = `/products/${product}/m3d`;

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
  const enc = encodeURIComponent;
  const del = async (path: string) => {
    const res = await transport.fetch(path, { method: "DELETE" });
    if (!res.ok && res.status !== 404) throw new HttpError(res.status, await errorMessage(res));
  };

  const notHere = <T>(): Promise<T> =>
    Promise.reject(new Error("This is set up by whoever runs this service, not from this page."));

  /** What the setup card reads, from the product's status: a worker that is ready is "installed". */
  async function hostedComponent(): Promise<Model3dComponent> {
    const s = await json<Model3dStatus>(`${base}/status`);
    return {
      installed: s.ready,
      source: "worker",
      plan: { supported: true, platform: "worker", bytes: 0, parts: [], found: null },
      progress: {
        state: s.ready ? "ready" : "idle",
        step: null,
        message: s.problem ?? "",
        done_bytes: 0,
        total_bytes: 0,
      },
      fit: s.fit,
      about: HOSTED_ABOUT,
    };
  }

  return {
    component: () => (hosted ? hostedComponent() : json<Model3dComponent>("/desktop/model3d")),
    install: (confirmBytes) =>
      hosted
        ? notHere<Model3dComponent>()
        : json<Model3dComponent>(
            "/desktop/model3d/install",
            send("POST", { confirm_bytes: confirmBytes }),
          ),
    cancelInstall: () =>
      hosted
        ? notHere<Model3dComponent>()
        : json<Model3dComponent>("/desktop/model3d/install/cancel", { method: "POST" }),
    uninstall: () =>
      hosted
        ? notHere<{ freed_bytes: number } & Model3dComponent>()
        : json("/desktop/model3d/uninstall", { method: "POST" }),
    status: () => json<Model3dStatus>(`${base}/status`),
    addPicture: (picture, name = "") =>
      json<PictureInput>(`${base}/inputs?name=${enc(name)}`, {
        method: "POST",
        headers: { "content-type": picture.type || "application/octet-stream" },
        body: picture,
      }),
    picture: (id) => json<PictureInput>(`${base}/inputs/${enc(id)}`),
    pictureImage: (id, which) => objectUrl(`${base}/inputs/${enc(id)}/${which}`),
    removePicture: (id) => del(`${base}/inputs/${enc(id)}`),
    make: (request) => json<Model3d>(`${base}/models`, send("POST", request)),
    list: async () => (await json<{ items: Model3d[] }>(`${base}/models`)).items,
    get: (id) => json<Model3d>(`${base}/models/${enc(id)}`),
    cancel: (id) =>
      json<Model3d & { stopped: boolean }>(`${base}/models/${enc(id)}/cancel`, { method: "POST" }),
    again: (id) => json<Model3d>(`${base}/models/${enc(id)}/again`, { method: "POST" }),
    rename: (id, title) => json<Model3d>(`${base}/models/${enc(id)}`, send("PATCH", { title })),
    remove: (id) => del(`${base}/models/${enc(id)}`),
    fileUrl: (id, which) => objectUrl(`${base}/models/${enc(id)}/${which}`),
    exportCopy: (id, path) =>
      json<{ name: string; path: string }>(
        `${base}/models/${enc(id)}/export`,
        send("POST", path ? { path } : undefined),
      ),
  };
}

/** "About 12 minutes" from a time in seconds; at least a minute. */
export function minutes(seconds: number): string {
  const m = Math.max(1, Math.round(seconds / 60));
  return m === 1 ? "about a minute" : `about ${m} minutes`;
}

/** "8.1 GB" for a download size. */
export function gigabytes(bytes: number): string {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`;
}
