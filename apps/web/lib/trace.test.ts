import { describe, expect, it } from "vitest";
import { traceHeaders, traceparent } from "./trace";

describe("traceparent", () => {
  it("starts a new trace in the W3C shape", () => {
    expect(traceparent()).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
    expect(traceparent()).not.toBe(traceparent());
  });

  it("continues a trace it was given, with a span of its own", () => {
    const given = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
    const next = traceparent(given);
    expect(next.slice(3, 35)).toBe("4bf92f3577b34da6a3ce929d0e0e4736");
    expect(next.slice(36, 52)).not.toBe("00f067aa0ba902b7");
  });

  it("starts again on a malformed or empty one", () => {
    for (const bad of ["junk", `00-${"0".repeat(32)}-00f067aa0ba902b7-01`]) {
      expect(traceparent(bad).slice(3, 35)).not.toBe("0".repeat(32));
      expect(traceparent(bad)).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
    }
    const req = new Request("http://x", { headers: { traceparent: "junk" } });
    expect(traceHeaders(req).traceparent).toMatch(/^00-[0-9a-f]{32}/);
  });
});
