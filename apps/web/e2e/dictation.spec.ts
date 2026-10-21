import { type Page, expect, test } from "@playwright/test";
import { mockApi } from "./mock-api";

// Dictation in the chat box (ADR-0083, decision 5), on the chat. Chromium gives the page a fake microphone
// (a steady beep), so the real recorder runs: the worklet is fetched from the app's own `/recorder-worklet.js`, the clip is averaged
// down to a 16 kHz mono WAV in the page, and what is posted to the engine is checked byte for byte at the header. The engine's answer
// is scripted. `@layout` cases run in CI.

test.use({
  permissions: ["microphone"],
  launchOptions: {
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  },
});

async function setup(page: Page) {
  await mockApi(page);
  await page.route("**/api/products/wasifyai-assistant/options", (route) =>
    route.fulfill({ json: { thinking: false } }),
  );
}

const box = (page: Page) => page.getByRole("textbox", { name: "Message" });
const mic = (page: Page) => page.getByRole("button", { name: /^Mic\./ });
const stop = (page: Page) => page.getByRole("button", { name: /^Stop\. Listening/ });

async function noSideScroll(page: Page) {
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(1);
}

test.describe("the chat", () => {
  test("record, stop, and the words land in the box without being sent @layout", async ({
    page,
  }) => {
    await setup(page);
    const posted: { type: string; wav: Buffer }[] = [];
    let runs = 0;
    await page.route("**/api/products/wasifyai-assistant/runs", (route) => {
      runs += 1;
      return route.abort();
    });
    await page.route("**/api/products/wasifyai-voice/dictation", async (route) => {
      const req = route.request();
      const body = req.postDataBuffer() ?? Buffer.alloc(0);
      const at = body.indexOf("RIFF");
      posted.push({ type: req.headers()["content-type"] ?? "", wav: body.subarray(at) });
      await route.fulfill({
        json: { text: "buy two apples", seconds: 1.5, model: "hosted-transcribe", displaced: null },
      });
    });
    await page.addInitScript(() => {
      const open = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      const streams: MediaStream[] = [];
      (window as unknown as { __streams: MediaStream[] }).__streams = streams;
      navigator.mediaDevices.getUserMedia = async (c) => {
        const stream = await open(c);
        streams.push(stream);
        return stream;
      };
    });
    await page.goto("/");
    await box(page).fill("Please");
    await expect(mic(page)).toBeVisible();
    await mic(page).click();

    // the recording is visible, with the name of the microphone that listens
    await expect(page.getByText(/Listening with .+ · 0:0\d/)).toBeVisible();
    await expect(stop(page)).toHaveAttribute("aria-pressed", "true");
    await page.waitForTimeout(1500);
    await stop(page).click();

    await expect(box(page)).toHaveValue("Please buy two apples");
    expect(runs, "dictated words are never sent by themselves").toBe(0);
    await expect(page.getByText("Transcribing…")).toBeHidden();

    // what was uploaded: a 16 kHz mono 16-bit WAV of about the length that was recorded
    expect(posted).toHaveLength(1);
    expect(posted[0]?.type).toMatch(/^multipart\/form-data/);
    const wav = posted[0]?.wav as Buffer;
    expect(wav.toString("latin1", 0, 4)).toBe("RIFF");
    expect(wav.toString("latin1", 8, 12)).toBe("WAVE");
    expect(wav.readUInt16LE(20)).toBe(1); // PCM
    expect(wav.readUInt16LE(22)).toBe(1); // mono
    expect(wav.readUInt32LE(24)).toBe(16000);
    expect(wav.readUInt16LE(34)).toBe(16);
    const seconds = wav.readUInt32LE(40) / 2 / 16000;
    expect(seconds).toBeGreaterThan(1);
    expect(seconds).toBeLessThan(4);

    // the microphone was let go: every track of the stream that was opened has ended
    const states = await page.evaluate(() =>
      (window as unknown as { __streams: MediaStream[] }).__streams.flatMap((s) =>
        s.getTracks().map((t) => t.readyState),
      ),
    );
    expect(states.length).toBeGreaterThan(0);
    expect(states.every((x) => x === "ended")).toBe(true);
    await noSideScroll(page);
  });

  test("a refused microphone is said in plain words @layout", async ({ page }) => {
    await setup(page);
    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = () =>
        Promise.reject(new DOMException("denied", "NotAllowedError"));
    });
    await page.goto("/");
    await mic(page).click();
    const alert = page.getByRole("alert", { name: "Dictation" });
    await expect(alert).toContainText("The microphone is turned off for this app");
    await expect(alert).not.toContainText("NotAllowedError");
    await expect(mic(page)).toBeEnabled();
  });

  test("looks right while it listens @visual", async ({ page }) => {
    await setup(page);
    await page.goto("/");
    await expect(mic(page)).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await mic(page).click();
    await expect(page.getByText(/Listening with/)).toBeVisible();
    await expect(page).toHaveScreenshot("dictation-next-listening.png");
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`${scheme}, 320 px: the Mic and the recording card fit and nothing scrolls sideways @layout`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.setViewportSize({ width: 320, height: 640 });
      await setup(page);
      await page.route("**/api/products/wasifyai-voice/dictation", (route) =>
        route.fulfill({ json: { text: "hello", seconds: 1, model: "m", displaced: null } }),
      );
      await page.goto("/");
      await expect(mic(page)).toBeVisible();
      const bar = await mic(page).boundingBox();
      expect(bar?.height ?? 0).toBeGreaterThanOrEqual(24);
      expect((bar?.x ?? 0) + (bar?.width ?? 0)).toBeLessThanOrEqual(320);
      await noSideScroll(page);

      await mic(page).click();
      const card = page.getByRole("region", { name: "Dictation" });
      await expect(card).toBeVisible();
      const c = await card.boundingBox();
      expect((c?.x ?? 0) + (c?.width ?? 0)).toBeLessThanOrEqual(320);
      await noSideScroll(page);
      await page.waitForTimeout(1200); // long enough to be a clip
      await stop(page).click();
      await expect(box(page)).toHaveValue("hello");
      await noSideScroll(page);
    });
  }
});
