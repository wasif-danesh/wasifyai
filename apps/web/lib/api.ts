// Server-side reads from the API. Pages are server components, so they call the API directly
// (the same network position as the BFF route handlers); the browser never does.
import { apiAuthHeaders } from "./api-token";
import { API_BASE_URL } from "./proxy";
import { traceHeaders } from "./trace";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const identity = await apiAuthHeaders();
  if (!identity) throw new ApiError(401, "sign in required");
  const res = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    headers: { ...identity, ...traceHeaders() },
  });
  if (!res.ok) throw new ApiError(res.status, `API ${path} answered ${res.status}`);
  return (await res.json()) as T;
}

/** A write to the API (POST or PUT with a JSON body). Returns the status and parsed body instead of
 * throwing, because the admin forms show the API's own reasons (a rejected model, a bad field). */
export async function apiSend(
  method: "POST" | "PUT",
  path: string,
  body?: unknown,
): Promise<{ status: number; data: unknown }> {
  const identity = await apiAuthHeaders();
  if (!identity) return { status: 401, data: { detail: "sign in required" } };
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    cache: "no-store",
    headers: { ...identity, ...traceHeaders(), "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    // no body
  }
  return { status: res.status, data };
}
