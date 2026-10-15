import { HttpError, type Transport, createRunClient } from "@wasifyai/client";

// The calls themselves live in packages/client and are written against engine paths. This file is the
// web app's transport (every call goes to the BFF under /api, with the session cookie) and keeps the
// function names the screens already use.
export { HttpError };
export type {
  Approval,
  Enhanced,
  SongInput,
  UploadedImage,
  UploadedMedia,
} from "@wasifyai/client";

export const PRODUCT = "wasifyai-music";

const transport: Transport = {
  fetch: (path, init) => fetch(`/api${path}`, init),
  onUnauthorized() {
    // the session ended: sign in again and come back
    if (typeof window !== "undefined") {
      window.location.assign(`/signin?next=${encodeURIComponent(window.location.pathname)}`);
    }
  },
};

/** The client the web screens use. A single object, so hooks that depend on it stay stable. */
export const webClient = createRunClient(transport);

export const startRun = (
  input: object,
  signal: AbortSignal,
  onEvent: Parameters<typeof webClient.startRun>[3],
  product: string = PRODUCT,
) => webClient.startRun(product, input, signal, onEvent);

export const resumeRun = webClient.resumeRun;
export const watchRun = webClient.watchRun;
export const uploadImage = webClient.uploadImage;
export const uploadMedia = webClient.uploadMedia;
export const deleteUpload = webClient.deleteUpload;
export const deleteMediaUpload = webClient.deleteMediaUpload;
export const enhancePrompt = webClient.enhancePrompt;
