// The engine's optional components (stage F2): one route family for every component (`/components`) and the
// `component` events on the window's event stream, so a card follows an install without asking.
import type { Transport } from "./transport";
import { HttpError } from "./transport";

/** Where an install is: the step (1-based, out of `count`), and the bytes of a download. */
export type InstallStepProgress = {
  component: string;
  step: string;
  label: string;
  index: number;
  count: number;
  bytes_done: number | null;
  bytes_total: number | null;
  /** the installer's latest line of output */
  detail: string | null;
};

/** A component's state; the same shape the shell's own installers report. */
export type ComponentState =
  | { state: "unsupported"; reason: string }
  | { state: "not_installed"; needs_bytes: number }
  | { state: "installing"; progress: InstallStepProgress }
  | { state: "installed"; version: string; accelerator: string }
  | { state: "failed"; message: string; step: string | null };

export type ComponentView = { id: string; title: string; status: ComponentState };

async function json<T>(transport: Transport, path: string, init?: RequestInit): Promise<T> {
  const res = await transport.fetch(path, init);
  if (!res.ok) {
    let detail = `The engine answered ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // not JSON
    }
    throw new HttpError(res.status, detail);
  }
  return (await res.json()) as T;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export function createComponentsApi(transport: Transport) {
  return {
    list: () => json<{ components: ComponentView[] }>(transport, "/components"),
    get: (id: string) => json<ComponentView>(transport, `/components/${id}`),
    /** `confirmBytes`: the size the person was shown; a repair fetches only what is missing. */
    install: (id: string, confirmBytes: number | null, repair = false) =>
      json<ComponentView>(
        transport,
        `/components/${id}/install`,
        post({ confirm_bytes: confirmBytes, repair }),
      ),
    cancel: (id: string) => json<ComponentView>(transport, `/components/${id}/cancel`, post({})),
    uninstall: (id: string) =>
      json<ComponentView & { freed_bytes: number }>(
        transport,
        `/components/${id}/uninstall`,
        post({}),
      ),
    /** The `component` events of the window's event stream. Ends when `signal` aborts. */
    async events(
      onStatus: (id: string, status: ComponentState) => void,
      signal: AbortSignal,
    ): Promise<void> {
      const res = await transport.fetch("/desktop/events", { signal });
      if (!res.ok || !res.body) throw new HttpError(res.status, "no event stream");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return;
        buf += decoder.decode(value, { stream: true });
        let idx = buf.indexOf("\n\n");
        while (idx !== -1) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          idx = buf.indexOf("\n\n");
          const data = block
            .split("\n")
            .filter((l) => l.startsWith("data:"))
            .map((l) => l.slice(5).trim())
            .join("\n");
          if (!data) continue;
          try {
            const event = JSON.parse(data) as {
              kind?: string;
              id?: string;
              status?: ComponentState;
            };
            if (event.kind === "component" && event.id && event.status)
              onStatus(event.id, event.status);
          } catch {
            // not ours
          }
        }
      }
    },
  };
}

export type ComponentsApi = ReturnType<typeof createComponentsApi>;
