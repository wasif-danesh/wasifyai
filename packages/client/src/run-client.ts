import { type ParsedEvent, parseSse } from "./sse";
import { HttpError, type Transport, errorMessage } from "./transport";

export type SongInput = { idea: string; genre?: string; mood?: string };
export type Approval = {
  action: "approve" | "regenerate";
  title?: string;
  lyrics?: string;
  style?: string;
};

export type UploadedImage = {
  upload_id: string;
  key: string;
  width: number;
  height: number;
  bytes: number;
};

export type UploadedMedia = { upload_id: string; key: string; seconds: number; bytes: number };

export type Enhanced = { prompt: string; changed: boolean };

export type OnEvent = (e: ParsedEvent) => void;

const JSON_HEADERS = { "content-type": "application/json", accept: "text/event-stream" };

/**
 * The calls the create screens make: start, watch and resume a run (server-sent events), upload a
 * picture or a recording, and enhance a prompt. Everything goes through `transport`, so the same
 * client serves the web app and the desktop app.
 */
export function createRunClient(transport: Transport) {
  async function request(path: string, init?: RequestInit): Promise<Response> {
    const res = await transport.fetch(path, init);
    if (res.status === 401) transport.onUnauthorized?.();
    return res;
  }

  async function stream(path: string, init: RequestInit, onEvent: OnEvent): Promise<void> {
    const res = await request(path, init);
    if (!res.ok || !res.body) throw new HttpError(res.status, await errorMessage(res));
    for await (const e of parseSse(res.body)) onEvent(e);
  }

  async function json<T>(path: string, init: RequestInit): Promise<T> {
    const res = await request(path, init);
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as T;
  }

  return {
    /** Start a run of a product's graph and follow its events until the stream ends. With `runId` (a UUID the
     * caller chose) the run has that id from the start, so a connection that breaks before the first event can still
     * be re-attached; starting again with the same id attaches to that run instead of making a second one. */
    startRun(
      product: string,
      input: object,
      signal: AbortSignal,
      onEvent: OnEvent,
      runId?: string,
    ) {
      return stream(
        `/products/${product}/runs`,
        {
          method: "POST",
          headers: JSON_HEADERS,
          body: JSON.stringify(runId ? { input, run_id: runId } : { input }),
          signal,
        },
        onEvent,
      );
    },

    /** Ask the engine to stop a run (the Stop button). A run that already ended is not an error. */
    async cancelRun(runId: string): Promise<void> {
      const res = await request(`/runs/${runId}/cancel`, { method: "POST" });
      if (!res.ok && res.status !== 404 && res.status !== 409)
        throw new HttpError(res.status, await errorMessage(res));
    },

    /** Answer a run's interrupt (approve, edit) and follow it on. */
    resumeRun(runId: string, value: Approval, signal: AbortSignal, onEvent: OnEvent) {
      return stream(
        `/runs/${runId}/resume`,
        { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ value }), signal },
        onEvent,
      );
    },

    /** Re-attach to a run; the server replays only the events after `lastSeq`. */
    watchRun(runId: string, lastSeq: number, signal: AbortSignal, onEvent: OnEvent) {
      return stream(
        `/runs/${runId}/events`,
        { headers: { accept: "text/event-stream", "last-event-id": String(lastSeq) }, signal },
        onEvent,
      );
    },

    /** Send the user's picture to the server (ADR-0035). The body is the file itself. */
    uploadImage(product: string, file: File, signal?: AbortSignal): Promise<UploadedImage> {
      return json<UploadedImage>(`/products/${product}/uploads/images`, {
        method: "POST",
        headers: { "content-type": file.type || "application/octet-stream" },
        body: file,
        signal,
      });
    },

    /** Send the user's recording or video file to the server (ADR-0043). */
    uploadMedia(product: string, file: Blob, signal?: AbortSignal): Promise<UploadedMedia> {
      return json<UploadedMedia>(`/products/${product}/uploads/media`, {
        method: "POST",
        headers: { "content-type": file.type || "application/octet-stream" },
        body: file,
        signal,
      });
    },

    /** Take back a picture that was uploaded but not used (ADR-0039). Failures are not worth
     * showing: the server deletes unused uploads after 24 hours anyway. `keepalive` lets it finish
     * while the page unloads. */
    async deleteUpload(product: string, uploadId: string): Promise<void> {
      try {
        await request(`/products/${product}/uploads/images/${uploadId}`, {
          method: "DELETE",
          keepalive: true,
        });
      } catch {
        // see above
      }
    },

    /** Take back a recording that was uploaded but not used. */
    async deleteMediaUpload(product: string, uploadId: string): Promise<void> {
      try {
        await request(`/products/${product}/uploads/media/${uploadId}`, {
          method: "DELETE",
          keepalive: true,
        });
      } catch {
        // the server deletes unused uploads after 24 hours anyway
      }
    },

    /** Ask the product to rewrite the user's prompt (ADR-0038). A refusal or a busy model arrives
     * as an `HttpError` whose message is plain text for the user. */
    enhancePrompt(
      product: string,
      input: { kind: string; prompt: string; uploadId?: string },
      signal?: AbortSignal,
    ): Promise<Enhanced> {
      return json<Enhanced>(`/products/${product}/prompt/enhance`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          kind: input.kind,
          prompt: input.prompt,
          upload_id: input.uploadId ?? null,
        }),
        signal,
      });
    },
  };
}

export type RunClient = ReturnType<typeof createRunClient>;
