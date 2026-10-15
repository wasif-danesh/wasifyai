// SPDX-License-Identifier: AGPL-3.0-only
// A self-test of the whole window, run inside the real webview when the shell is started with
// WASIFYAI_SMOKE=1: it types a prompt into the create form, presses the button, waits for the picture
// to load from the engine, and tells the shell how it went (the shell exits 0 or 1). It drives the same
// DOM a person would, so CORS, the content security policy and the signed file link are all exercised.
import { invoke } from "@tauri-apps/api/core";

const PROMPT = "a red ceramic teapot on a wooden table";
const TIMEOUT_MS = 90_000;

export const smokeEnabled = () => invoke<boolean>("smoke_enabled");

const report = (ok: boolean, detail: string) => invoke<void>("smoke_report", { ok, detail });

async function until<T>(what: string, find: () => T | null | undefined | false): Promise<T> {
  const deadline = Date.now() + TIMEOUT_MS;
  for (;;) {
    const found = find();
    if (found) return found;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 100));
  }
}

function type(el: HTMLTextAreaElement, text: string) {
  // React listens to the input event; the native setter is what it expects to see change
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  set?.call(el, text);
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

export async function runSmoke(): Promise<void> {
  try {
    const box = await until("the prompt box", () => document.querySelector("textarea"));
    type(box, PROMPT);
    const go = await until("the Make my image button", () =>
      [...document.querySelectorAll("button")].find(
        (b) => b.textContent?.includes("Make my image") && !b.disabled,
      ),
    );
    go.click();

    const picture = await until("the finished picture", () => {
      const img = document.querySelector<HTMLImageElement>(`figure img[alt="${PROMPT}"]`);
      return img?.complete && img.naturalWidth > 0 ? img : null;
    });
    if (!picture.src.startsWith("http://127.0.0.1:") || !picture.src.includes("/files/")) {
      throw new Error(`the picture did not come from the engine: ${picture.src}`);
    }
    await until("the ready message", () =>
      document.body.textContent?.includes("Your image is ready"),
    );
    await report(
      true,
      `picture ${picture.naturalWidth}x${picture.naturalHeight} from ${picture.src}`,
    );
  } catch (e) {
    await report(false, e instanceof Error ? e.message : String(e)).catch(() => {});
  }
}
