import { HttpError, type Transport, createRunClient } from "@wasifyai/client";

// The calls themselves live in packages/client and are written against engine paths. This file is the
// web app's transport (every call goes to the BFF under /api, with the session cookie).
export { HttpError };

export const transport: Transport = {
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
