// The window watches part changes over one stream, however many screens listen: a stream each used up the
// connections the window may hold open to the engine, and the first run's model list waited behind them forever.
import { describe, expect, it, vi } from "vitest";

const opened: AbortSignal[] = [];
let send: ((id: string, s: unknown) => void) | null = null;
vi.mock("./api", () => ({
  componentsApi: {
    events: (fn: (id: string, s: unknown) => void, signal: AbortSignal) => {
      opened.push(signal);
      send = fn;
      return new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve()));
    },
  },
}));

const { onComponentStatus } = await import("./components");

describe("watching part changes", () => {
  it("opens one stream for every listener, tells each, and closes it with the last", async () => {
    const a = vi.fn();
    const b = vi.fn();
    const offA = await onComponentStatus(a);
    const offB = await onComponentStatus(b);
    expect(opened).toHaveLength(1);
    send?.("comfyui", { state: "installed" });
    expect(a).toHaveBeenCalledWith("comfyui", { state: "installed" });
    expect(b).toHaveBeenCalledWith("comfyui", { state: "installed" });
    offA();
    expect(opened[0]?.aborted).toBe(false);
    offB();
    expect(opened[0]?.aborted).toBe(true);
    const offC = await onComponentStatus(vi.fn());
    expect(opened).toHaveLength(2); // a new listener later opens it again
    offC();
  });
});
