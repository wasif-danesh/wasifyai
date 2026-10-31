import { apiAuthHeaders } from "./api-token";
import { traceHeaders } from "./trace";

// The BFF: route handlers forward to FastAPI and pass the response through unchanged, so event
// streams stay streams. The browser never calls FastAPI directly.
export const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PRODUCT = /^[a-z0-9][a-z0-9-]{0,63}$/;

/** Path segments are validated, not just encoded: only the shapes we expect reach the API. */
export function isUuid(value: string): boolean {
  return UUID.test(value);
}
export function isProductId(value: string): boolean {
  return PRODUCT.test(value);
}

export function badRequest(message: string): Response {
  return Response.json({ detail: message }, { status: 400 });
}

type ProxyOptions = {
  method?: string;
  body?: string | ReadableStream<Uint8Array> | null;
  headers?: Record<string, string>;
};

export async function proxy(
  req: Request,
  path: string,
  opts: ProxyOptions = {},
): Promise<Response> {
  const identity = await apiAuthHeaders();
  if (!identity) return Response.json({ detail: "sign in required" }, { status: 401 });
  const init: RequestInit & { duplex?: "half" } = {
    method: opts.method ?? req.method,
    headers: {
      ...opts.headers,
      ...identity,
      ...traceHeaders(req),
      // a media player asks for a file in pieces
      ...(req.headers.get("range") ? { range: req.headers.get("range") as string } : {}),
    },
    body: opts.body,
    signal: req.signal,
    cache: "no-store",
  };
  // an upload is passed through as a stream, never held in memory here
  if (opts.body && typeof opts.body !== "string") init.duplex = "half";
  const upstream = await fetch(`${API_BASE_URL}${path}`, init);
  const type = upstream.headers.get("content-type") ?? "application/json";
  const headers: Record<string, string> = { "content-type": type };
  // what a file download needs to arrive as a download
  for (const name of [
    "content-disposition",
    "content-length",
    "cache-control",
    "x-content-type-options",
    // what the player's page needs (ADR-0096): its own limits, and a video in pieces
    "content-security-policy",
    "accept-ranges",
    "content-range",
  ]) {
    const value = upstream.headers.get(name);
    if (value) headers[name] = value;
  }
  if (type.startsWith("text/event-stream")) {
    // no compression or buffering anywhere on the way to the browser
    headers["cache-control"] = "no-cache, no-transform";
    headers["x-accel-buffering"] = "no";
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
