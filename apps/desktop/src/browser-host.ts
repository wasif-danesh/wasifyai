// SPDX-License-Identifier: AGPL-3.0-only
// The Browser tab's pages (a coding session): a second webview the shell lays over the tab's area
// (src-tauri/src/browser.rs). A page in it can call none of the shell's commands; only this window can.
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { BrowserHost } from "@wasifyai/ui";

export const browserHost: BrowserHost = {
  show: (area, url) => invoke("browser_show", { ...area, url: url ?? null }),
  hide: () => void invoke("browser_hide").catch(() => {}),
  close: () => void invoke("browser_close").catch(() => {}),
  go: (to) => invoke("browser_go", { to }),
  text: () => invoke("browser_text"),
  onChange: (told) => {
    const stop = listen<{ url: string; loading: boolean }>("code-browser-changed", (e) =>
      told(e.payload),
    );
    return () => void stop.then((off) => off()).catch(() => {});
  },
  openOutside: (url) => void invoke("open_external", { url }).catch(() => {}),
};

/** "Open Wasify AI when I log in, and keep it in the menu bar" (src-tauri/src/stay_open.rs). */
export const stayOpen = {
  get: () => invoke<{ supported: boolean; on: boolean }>("stay_open_get"),
  set: (on: boolean) => invoke<{ supported: boolean; on: boolean }>("stay_open_set", { on }),
};
