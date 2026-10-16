/**
 * How a screen reaches the engine. A client is written once against engine paths (`/products/{id}/runs`);
 * each app supplies the transport that gets a request there: the web app sends it to its BFF under
 * `/api` with the session cookie, the desktop app sends it to the loopback engine with the shell's token.
 */
export type Transport = {
  /** Like `fetch`, for an engine path such as `/products/wasifyai-image/runs`. */
  fetch(path: string, init?: RequestInit): Promise<Response>;
  /** Called when the engine answers 401: the session ended (the web app goes to sign-in). */
  onUnauthorized?(): void;
};

/** A non-2xx answer. `message` is plain text a person can read. */
export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    // a product's own refusal: `{code, message}`
    if (typeof body?.detail?.message === "string") return body.detail.message;
  } catch {
    // not JSON
  }
  return `The server answered ${res.status}`;
}
