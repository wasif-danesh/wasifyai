// SPDX-License-Identifier: AGPL-3.0-only
// A self-test of the whole window, run inside the real webview when the shell is started with
// WASIFYAI_SMOKE=1: it types a prompt into the create form, presses the button, waits for the picture
// to load from the engine, and tells the shell how it went (the shell exits 0 or 1). It drives the same
// DOM a person would, so CORS, the content security policy and the signed file link are all exercised.
import { invoke } from "@tauri-apps/api/core";

const PROMPT = "a red ceramic teapot on a wooden table";
const TIMEOUT_MS = 90_000;
const INSTALL_TIMEOUT_MS = 30 * 60_000;

export const smokeEnabled = () => invoke<boolean>("smoke_enabled");
/** The optional component the self-test should set up instead of making an image, if any. */
export const smokeComponent = () => invoke<string | null>("smoke_component");

const report = (ok: boolean, detail: string) => invoke<void>("smoke_report", { ok, detail });

async function until<T>(
  what: string,
  find: () => T | null | undefined | false,
  timeoutMs = TIMEOUT_MS,
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
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
    window.location.hash = "/images/create"; // the create screen
    await new Promise((r) => setTimeout(r, 100));
    const box = await until("the prompt box", () => document.querySelector("textarea"));
    type(box, PROMPT);
    const go = await until("the Generate button", () =>
      [...document.querySelectorAll("button")].find(
        (b) => b.textContent?.trim() === "Generate" && !b.disabled,
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

    // the recipe: favourite it, read its seed, then make it again and expect the same recipe
    const buttonNamed = (name: string | RegExp) => () =>
      [...document.querySelectorAll("button")].find((b) =>
        typeof name === "string" ? b.textContent?.trim() === name : name.test(b.textContent ?? ""),
      );
    const readSeed = async () => {
      if (!document.querySelector("dl")) (await until("Recipe", buttonNamed("Recipe"))).click();
      const dd = await until("the seed", () => document.querySelector("dl dd.font-mono"));
      return Number(dd.textContent);
    };
    (await until("Add to favourites", buttonNamed("Add to favourites"))).click();
    await until("the favourite mark", buttonNamed("Favourite"));
    const seed = await readSeed();
    if (!Number.isInteger(seed)) throw new Error(`the recipe has no seed: ${seed}`);
    (await until("Make it again", buttonNamed(/Make it again/))).click();
    const again = await until("the second picture", () => {
      const img = document.querySelector<HTMLImageElement>(`figure img[alt="${PROMPT}"]`);
      return img?.complete && img.naturalWidth > 0 && img.src !== picture.src ? img : null;
    });
    await until("the second recipe", buttonNamed(/Make it again/));
    const seedAgain = await readSeed();
    if (seedAgain !== seed) throw new Error(`the seed changed: ${seed} then ${seedAgain}`);
    const size = `${again.naturalWidth}x${again.naturalHeight}`;
    if (size !== `${picture.naturalWidth}x${picture.naturalHeight}`) {
      throw new Error(`the second picture has another size: ${size}`);
    }
    await report(
      true,
      `picture ${picture.naturalWidth}x${picture.naturalHeight} from ${picture.src}; again with seed ${seed}`,
    );
  } catch (e) {
    await report(false, e instanceof Error ? e.message : String(e)).catch(() => {});
  }
}

/** Set up the image engine the way a person does: press the button, wait until it says it is installed. */
export async function runComponentSmoke(): Promise<void> {
  const started = Date.now();
  try {
    window.location.hash = "/settings"; // where the image engine is set up
    await new Promise((r) => setTimeout(r, 100));
    const go = await until("the Set up image generation button", () =>
      [...document.querySelectorAll("button")].find(
        (b) => b.textContent?.includes("Set up image generation") && !b.disabled,
      ),
    );
    go.click();
    const verdict = await until(
      "the image engine to be installed",
      () => {
        const text = document.body.textContent ?? "";
        if (text.includes("Image engine installed")) return "installed";
        if (text.includes("could not be set up")) return "failed";
        return null;
      },
      INSTALL_TIMEOUT_MS,
    );
    const secs = Math.round((Date.now() - started) / 1000);
    if (verdict === "failed") {
      const notice = document.querySelector('[role="alert"]')?.textContent ?? "no message";
      await report(false, `setup failed after ${secs}s: ${notice}`);
      return;
    }
    const line =
      [...document.querySelectorAll("p")].find((p) =>
        p.textContent?.startsWith("Image engine installed"),
      )?.textContent ?? "";
    await report(true, `image engine installed in ${secs}s: ${line}`);
  } catch (e) {
    await report(false, e instanceof Error ? e.message : String(e)).catch(() => {});
  }
}
