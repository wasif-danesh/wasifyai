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
    // the home screen is the assistant (ADR-0057): say hello and wait for an answer or a plain error
    // (with no chat model chosen, as on a fresh computer, the error says what to do)
    window.location.hash = "/";
    await new Promise((r) => setTimeout(r, 150));
    const hello = await until("the message box", () =>
      document.querySelector<HTMLTextAreaElement>('textarea[placeholder="Ask anything"]'),
    );
    type(hello, "Hello");
    (
      await until("the Send button", () =>
        [...document.querySelectorAll<HTMLButtonElement>("button")].find(
          (b) => b.getAttribute("aria-label") === "Send" && !b.disabled,
        ),
      )
    ).click();
    // the answer is under way while a Stop button is there; an error is a notice
    const stopButton = () =>
      [...document.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Stop");
    const failed = () => document.body.textContent?.includes("That did not work");
    await until("the answer to start", () => stopButton() || failed());
    await until("the answer to finish", () => !stopButton());
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
    // the Models screen lists what other tools left here (ADR-0063): the first scan finishes by itself
    window.location.hash = "/models";
    await until("the found models", () => {
      const text = document.body.textContent ?? "";
      return text.includes("Found on this computer") && !text.includes("Looking in the folders")
        ? text
        : null;
    });
    // Discover asks before it contacts anyone (ADR-0064), and the recommended list needs no network
    const discover = await until("the Discover tab", () =>
      [...document.querySelectorAll('[role="tab"]')].find((b) => b.textContent === "Discover"),
    );
    (discover as HTMLElement).click();
    await until("the recommended models", () =>
      document.body.textContent?.includes("Recommended to start with"),
    );
    (
      [...document.querySelectorAll('[role="tab"]')].find((b) => b.textContent === "On device") as
        | HTMLElement
        | undefined
    )?.click();
    await until("the result of the look", () => {
      const text = document.body.textContent ?? "";
      return /Looked (just now|\d+ minutes? ago)|No models from other tools|Looking is turned off/.test(
        text,
      );
    });
    await report(
      true,
      `picture ${picture.naturalWidth}x${picture.naturalHeight} from ${picture.src}; again with seed ${seed}`,
    );
  } catch (e) {
    // what the window was saying when it gave up makes a CI log readable
    const notice = document.querySelector('[role="alert"]')?.textContent?.trim().slice(0, 200);
    const message = e instanceof Error ? e.message : String(e);
    await report(false, notice ? `${message} (the window said: ${notice})` : message).catch(() => {});
  }
}

/** What the self-test presses and waits for, per optional component. */
const COMPONENTS = {
  comfyui: {
    button: "Set up image generation",
    done: "Image engine installed",
    failed: "could not be set up",
  },
  llamacpp: {
    button: "Set up the language engine",
    done: "Language engine installed",
    failed: "could not be set up",
  },
} as const;

/** Set up an optional engine the way a person does: press its button on Settings, wait until it says it
 * is installed. */
export async function runComponentSmoke(id: keyof typeof COMPONENTS = "comfyui"): Promise<void> {
  const started = Date.now();
  const words = COMPONENTS[id];
  try {
    window.location.hash = "/settings"; // where the engines are set up
    await new Promise((r) => setTimeout(r, 100));
    const go = await until(`the ${words.button} button`, () =>
      [...document.querySelectorAll("button")].find(
        (b) => b.textContent?.includes(words.button) && !b.disabled,
      ),
    );
    go.click();
    const verdict = await until(
      `${id} to be installed`,
      () => {
        const text = document.body.textContent ?? "";
        if (text.includes(words.done)) return "installed";
        if (text.includes(words.failed)) return "failed";
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
      [...document.querySelectorAll("p")].find((p) => p.textContent?.startsWith(words.done))
        ?.textContent ?? "";
    await report(true, `${id} installed in ${secs}s: ${line}`);
  } catch (e) {
    await report(false, e instanceof Error ? e.message : String(e)).catch(() => {});
  }
}
