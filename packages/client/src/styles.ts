// Styles (LoRAs) for the image screens (ADR-0091): the records the engine keeps in its `loras` folder, the
// engine's `/desktop/styles` routes. A request names a style by its id, never by a file or a path.
import type { Transport } from "./transport";
import { HttpError } from "./transport";

/** Whether a style was made for the model the image screens run (read from the file, never guessed). */
export type StyleFit = "fits" | "other" | "unsure";

export type Style = {
  id: string;
  title: string;
  /** "trained": made in Train; "file": added from this computer; "found": copied from another app; "hub": Hugging Face */
  source: {
    kind: "trained" | "file" | "found" | "hub";
    run?: string;
    tool?: string;
    repo?: string;
    file?: string;
  };
  sha256: string;
  size: number;
  /** the model the file says it was made for: "FLUX.2 klein 4B", "FLUX.1", … or null */
  model: string | null;
  fit: StyleFit;
  /** made for klein base: the look may not show on the distilled model the screens run */
  made_for_base: boolean;
  rank: number | null;
  /** parts of the file this app does not apply (said in one line) */
  unused_parts: number;
  trigger: string | null;
  added_at: number;
  /** false: made for another model; shown, never used */
  selectable: boolean;
};

/** A style another app keeps on this computer: copied in when it is chosen. */
export type FoundStyle = { id: string; title: string; tool: string; size: number };

/** A style we checked on the model (ADR-0091 S5), offered to get from Hugging Face; pinned by its checksum. */
export type RecommendedStyle = {
  title: string;
  repo: string;
  file: string;
  size: number;
  sha256: string;
  word: string;
  note: string;
};

export type StylesList = {
  styles: Style[];
  found: FoundStyle[];
  max: number;
  /** the desktop only; absent on the web */
  recommended?: RecommendedStyle[];
};

/** What a Hugging Face repository offers as styles (only `.safetensors`; the others say why not). */
export type HubStyleFiles = {
  repo: string;
  commit: string | null;
  gated: boolean;
  files: { name: string; size: number }[];
  refused: { name: string; why: string }[];
  /** the repository says it was made for klein base (true), the distilled klein (false), or not */
  made_for_base: boolean | null;
  trigger: string | null;
  /** the answer is from before: Hugging Face could not be reached */
  stale: boolean;
};

/** A style being fetched from Hugging Face; once done, the style kept or why the file was refused. */
export type HubStyleJob = {
  download: {
    id: string;
    status: "running" | "done" | "failed" | "cancelled";
    bytes_total: number;
    bytes_done: number;
    error: string;
  };
  style?: Style | null;
  refused?: string;
};

/**
 * A style in a picture: its id and how strongly it is applied (0.05 to 2). A recipe or a saved look also keeps its
 * checksum, title and source, so a style that came back under another id is found again, and a missing one is named.
 */
export type StyleChoice = {
  id: string;
  strength: number;
  sha256?: string;
  title?: string;
  source?: Style["source"] & { repo?: string; file?: string };
};

/** A saved look (ADR-0091 decision 11): a size, steps and styles by pointer, under a name. */
export type Look = {
  name: string;
  size: string | null;
  width: number | null;
  height: number | null;
  steps: number | null;
  styles: StyleChoice[];
  saved_at: number;
};

/** A refusal with the engine's code: `consent_needed` means browsing Hugging Face is not allowed yet. */
export class StyleError extends HttpError {
  constructor(
    status: number,
    message: string,
    readonly code: string | null,
  ) {
    super(status, message);
  }
}

async function json<T>(transport: Transport, path: string, init?: RequestInit): Promise<T> {
  const res = await transport.fetch(path, init);
  if (!res.ok) {
    let detail = `The engine answered ${res.status}`;
    let code: string | null = null;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (typeof body?.detail?.message === "string") {
        detail = body.detail.message;
        code = typeof body.detail.code === "string" ? body.detail.code : null;
      }
    } catch {
      // not JSON
    }
    throw new StyleError(res.status, detail, code);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const headers = { "content-type": "application/json" };

/**
 * The desktop's styles (`/desktop/styles`), or with `base` "/admin/styles" the web's admin side of the service's
 * styles (the list, Hugging Face, delete; ADR-0091 S5).
 */
export function createStylesApi(transport: Transport, base = "/desktop/styles") {
  const BASE = base;
  return {
    list: () => json<StylesList>(transport, BASE),
    /** A style from this computer: the file itself is sent; the engine checks it and keeps a copy. */
    importFile: (file: Blob, name: string) =>
      json<Style>(transport, `${BASE}/import?name=${encodeURIComponent(name)}`, {
        method: "POST",
        headers: { "content-type": "application/octet-stream" },
        body: file,
      }),
    /** A style another app keeps: the engine copies it in. */
    fromFound: (id: string) =>
      json<Style>(transport, `${BASE}/from-found`, {
        method: "POST",
        headers,
        body: JSON.stringify({ id }),
      }),
    update: (id: string, change: { title?: string; trigger?: string }) =>
      json<Style>(transport, `${BASE}/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers,
        body: JSON.stringify(change),
      }),
    /** Allow browsing Hugging Face (the same switch as the Model hub's): nothing is asked before. */
    allowHub: () =>
      json<{ enabled: boolean }>(transport, "/desktop/hub/consent", {
        method: "PUT",
        headers,
        body: JSON.stringify({ enabled: true }),
      }),
    /** The style files of a repository: `owner/name` or its address. */
    hubFiles: (repo: string) =>
      json<HubStyleFiles>(transport, `${BASE}/hub/files`, {
        method: "POST",
        headers,
        body: JSON.stringify({ repo }),
      }),
    /** Get one file the person confirmed, with the size they were shown. */
    hubDownload: (repo: string, file: string, bytes: number, sha256?: string) =>
      json<HubStyleJob["download"]>(transport, `${BASE}/hub/download`, {
        method: "POST",
        headers,
        body: JSON.stringify(sha256 ? { repo, file, bytes, sha256 } : { repo, file, bytes }),
      }),
    hubJob: (id: string) =>
      json<HubStyleJob>(transport, `${BASE}/hub/downloads/${encodeURIComponent(id)}`),
    looks: async () => (await json<{ looks: Look[] }>(transport, `${BASE}/looks`)).looks,
    /** Save the look under its name (the same name replaces it). */
    saveLook: (look: Omit<Look, "saved_at">) =>
      json<Look>(transport, `${BASE}/looks`, {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...look,
          styles: look.styles.map((s) => ({ id: s.id, strength: s.strength })),
        }),
      }),
    deleteLook: (name: string) =>
      json<void>(transport, `${BASE}/looks/${encodeURIComponent(name)}`, { method: "DELETE" }),
    /** Delete our copy of a style (never a file another app keeps). */
    remove: (id: string) =>
      json<void>(transport, `${BASE}/${encodeURIComponent(id)}`, { method: "DELETE" }),
  };
}

export type StylesApi = ReturnType<typeof createStylesApi>;

/**
 * The web's styles (ADR-0091 S5): the ones an admin added for the service, read only. A person chooses from them;
 * adding, getting and deleting are the admin's (Admin > Styles), so those calls say so.
 */
export function createServiceStylesApi(transport: Transport): StylesApi {
  const no = (): Promise<never> =>
    Promise.reject(new Error("Styles are added by an admin on this service."));
  return {
    list: () => json<StylesList>(transport, "/styles"),
    importFile: no,
    fromFound: no,
    update: no,
    allowHub: no,
    hubFiles: no,
    hubDownload: no,
    hubJob: no,
    looks: async () => [],
    saveLook: no,
    deleteLook: no,
    remove: no,
  };
}
