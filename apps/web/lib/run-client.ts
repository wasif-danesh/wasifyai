import { type ParsedEvent, parseSse } from "./sse";

export const PRODUCT = "wasifyai-music";

export type SongInput = { idea: string; genre?: string; mood?: string };
export type Approval = {
  action: "approve" | "regenerate";
  title?: string;
  lyrics?: string;
  style?: string;
};

export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // not JSON
  }
  return `The server answered ${res.status}`;
}

type OnEvent = (e: ParsedEvent) => void;

async function stream(url: string, init: RequestInit, onEvent: OnEvent): Promise<void> {
  const res = await fetch(url, init);
  if (res.status === 401 && typeof window !== "undefined") {
    // the session ended: sign in again and come back
    window.location.assign(`/signin?next=${encodeURIComponent(window.location.pathname)}`);
  }
  if (!res.ok || !res.body) throw new HttpError(res.status, await errorMessage(res));
  for await (const e of parseSse(res.body)) onEvent(e);
}

const JSON_HEADERS = { "content-type": "application/json", accept: "text/event-stream" };

export function startRun(
  input: object,
  signal: AbortSignal,
  onEvent: OnEvent,
  product: string = PRODUCT,
) {
  return stream(
    `/api/products/${product}/runs`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ input }), signal },
    onEvent,
  );
}

export type UploadedImage = {
  upload_id: string;
  key: string;
  width: number;
  height: number;
  bytes: number;
};

/** Send the user's picture to the server (ADR-0035). The body is the file itself. */
export async function uploadImage(
  product: string,
  file: File,
  signal?: AbortSignal,
): Promise<UploadedImage> {
  const res = await fetch(`/api/products/${product}/uploads/images`, {
    method: "POST",
    headers: { "content-type": file.type || "application/octet-stream" },
    body: file,
    signal,
  });
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.assign(`/signin?next=${encodeURIComponent(window.location.pathname)}`);
  }
  if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
  return (await res.json()) as UploadedImage;
}

export type UploadedMedia = { upload_id: string; key: string; seconds: number; bytes: number };

/** Send the user's recording or video file to the server (ADR-0043). The body is the file itself;
 * the server decides what it is from its first bytes and returns a clean copy's length. */
export async function uploadMedia(
  product: string,
  file: Blob,
  signal?: AbortSignal,
): Promise<UploadedMedia> {
  const res = await fetch(`/api/products/${product}/uploads/media`, {
    method: "POST",
    headers: { "content-type": file.type || "application/octet-stream" },
    body: file,
    signal,
  });
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.assign(`/signin?next=${encodeURIComponent(window.location.pathname)}`);
  }
  if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
  return (await res.json()) as UploadedMedia;
}

/** Take back a recording that was uploaded but not used. */
export async function deleteMediaUpload(product: string, uploadId: string): Promise<void> {
  try {
    await fetch(`/api/products/${product}/uploads/media/${uploadId}`, {
      method: "DELETE",
      keepalive: true,
    });
  } catch {
    // the server deletes unused uploads after 24 hours anyway
  }
}

export type Enhanced = { prompt: string; changed: boolean };

/** Ask the product to rewrite the user's prompt (ADR-0038). A refusal or a busy model arrives as an
 * `HttpError` whose message is plain text for the user. */
export async function enhancePrompt(
  product: string,
  input: { kind: string; prompt: string; uploadId?: string },
  signal?: AbortSignal,
): Promise<Enhanced> {
  const res = await fetch(`/api/products/${product}/prompt/enhance`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      kind: input.kind,
      prompt: input.prompt,
      upload_id: input.uploadId ?? null,
    }),
    signal,
  });
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.assign(`/signin?next=${encodeURIComponent(window.location.pathname)}`);
  }
  if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
  return (await res.json()) as Enhanced;
}

/** Take back a picture that was uploaded but not used (ADR-0039). Failures are not worth showing: the
 * server deletes unused uploads after 24 hours anyway. `keepalive` lets it finish while the page unloads. */
export async function deleteUpload(product: string, uploadId: string): Promise<void> {
  try {
    await fetch(`/api/products/${product}/uploads/images/${uploadId}`, {
      method: "DELETE",
      keepalive: true,
    });
  } catch {
    // see above
  }
}

export function resumeRun(runId: string, value: Approval, signal: AbortSignal, onEvent: OnEvent) {
  return stream(
    `/api/runs/${runId}/resume`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ value }), signal },
    onEvent,
  );
}

/** Re-attach to a run; the server replays only the events after `lastSeq`. */
export function watchRun(runId: string, lastSeq: number, signal: AbortSignal, onEvent: OnEvent) {
  return stream(
    `/api/runs/${runId}/events`,
    { headers: { accept: "text/event-stream", "last-event-id": String(lastSeq) }, signal },
    onEvent,
  );
}
