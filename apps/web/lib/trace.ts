// Traces (stage O1): every call the BFF makes to the API carries a W3C `traceparent`, so a run is one
// trace from here to the worker that does its work. The BFF continues one it was given (a proxy in
// front of it) or starts a new one; it does not export spans of its own yet.
const TRACEPARENT = /^00-([0-9a-f]{32})-([0-9a-f]{16})-0[01]$/;

function hex(bytes: number): string {
  const b = new Uint8Array(bytes);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

/** The `traceparent` for a call to the API: the incoming trace with a new span id, or a new trace. */
export function traceparent(incoming?: string | null): string {
  const m = incoming ? TRACEPARENT.exec(incoming) : null;
  const trace = m && !/^0+$/.test(m[1]) ? m[1] : hex(16);
  return `00-${trace}-${hex(8)}-01`;
}

export function traceHeaders(req?: Request): Record<string, string> {
  return { traceparent: traceparent(req?.headers.get("traceparent")) };
}
