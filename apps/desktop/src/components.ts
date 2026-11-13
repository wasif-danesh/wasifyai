// SPDX-License-Identifier: AGPL-3.0-only
// The optional components the person can add (the image engine, the language engine), set up by the engine since
// stage F2: its `/components` routes, and its `component` events on the window's event stream.
import { componentsApi } from "./api";
import type { ComponentStatus } from "./engine";

export async function componentStatus(id: string): Promise<ComponentStatus> {
  return (await componentsApi.get(id)).status;
}

/** Set a component up. `confirmBytes` is the size the person was shown (the card's own figure when not given);
 * the engine refuses a size that is out of date, so nothing is fetched that was not shown. */
export async function componentInstall(
  id: string,
  repair = false,
  confirmBytes?: number,
): Promise<void> {
  let bytes: number | null = confirmBytes ?? null;
  if (bytes === null && !repair) {
    const now = (await componentsApi.get(id)).status;
    if (now.state !== "not_installed") return;
    bytes = now.needs_bytes;
  }
  await componentsApi.install(id, bytes, repair);
}

/** Every status change of every component, until the returned function is called. */
export async function onComponentStatus(
  fn: (id: string, s: ComponentStatus) => void,
): Promise<() => void> {
  const stop = new AbortController();
  let wait = 1000;
  void (async () => {
    // the stream ends when the engine restarts: listen again, waiting a little longer each time
    while (!stop.signal.aborted) {
      try {
        await componentsApi.events((id, s) => {
          wait = 1000;
          fn(id, s);
        }, stop.signal);
      } catch {
        // the engine is not there yet, or restarting
      }
      if (stop.signal.aborted) return;
      await new Promise((r) => setTimeout(r, wait));
      wait = Math.min(wait * 2, 15_000);
    }
  })();
  return () => stop.abort();
}
