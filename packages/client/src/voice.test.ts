import { describe, expect, it } from "vitest";
import type { ParsedEvent } from "./sse";
import type { Transport } from "./transport";
import { createVoiceApi, makeSpeech } from "./voice";

const ev = (event: string, data: Record<string, unknown>): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as ParsedEvent;

function runs(events: ParsedEvent[]) {
  const seen: { product?: string; input?: Record<string, unknown> } = {};
  return {
    seen,
    startRun: async (p: string, input: object, _s: AbortSignal, on: (e: ParsedEvent) => void) => {
      seen.product = p;
      seen.input = input as Record<string, unknown>;
      for (const e of events) on(e);
    },
  };
}

function transport(answer: (path: string, init?: RequestInit) => Response) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const t: Transport = {
    fetch: async (path, init) => {
      calls.push({ path, init });
      return answer(path, init);
    },
  };
  return { t, calls };
}

const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("making a speech", () => {
  it("sends only what was chosen and returns the saved speech", async () => {
    const r = runs([
      ev("node", { label: "Making the speech" }),
      ev("done", {
        outputs: {
          status: "done",
          speech_id: "s1",
          seconds: 4.2,
          audio_url: "http://x/a.wav",
          sample_rate: 24000,
        },
      }),
    ]);
    const steps: string[] = [];
    const out = await makeSpeech(
      r,
      { text: "Hi", voice: "af_heart", options: {} },
      new AbortController().signal,
      (l) => steps.push(l),
    );
    expect(r.seen.product).toBe("wasifyai-voice");
    expect(r.seen.input).toEqual({ text: "Hi", voice: "af_heart" });
    expect(steps).toEqual(["Making the speech"]);
    expect(out).toEqual({
      ok: true,
      speech: { id: "s1", seconds: 4.2, audio_url: "http://x/a.wav", sample_rate: 24000 },
    });
  });

  it("returns a refusal and an engine error in words, and says so when the connection is lost", async () => {
    const refused = await makeSpeech(
      runs([
        ev("done", {
          outputs: {
            status: "refused",
            refusal: { code: "unknown_voice", message: "No such voice." },
          },
        }),
      ]),
      { text: "Hi", model: "m" },
      new AbortController().signal,
    );
    expect(refused).toEqual({ ok: false, code: "unknown_voice", message: "No such voice." });
    const failed = await makeSpeech(
      runs([ev("error", { code: "model_missing", message: "Get it in Models." })]),
      { text: "Hi" },
      new AbortController().signal,
    );
    expect(failed).toEqual({ ok: false, code: "model_missing", message: "Get it in Models." });
    const lost = await makeSpeech(runs([]), { text: "Hi" }, new AbortController().signal);
    expect(lost.ok).toBe(false);
    expect(!lost.ok && lost.code).toBe("lost");
  });
});

describe("the voice api", () => {
  it("asks for models by task and installs only with the size that was shown", async () => {
    const { t, calls } = transport(() => jsonRes({ models: [{ id: "kokoro-82m" }], runtime: {} }));
    const api = createVoiceApi(t);
    expect((await api.models("speak")).map((m) => m.id)).toEqual(["kokoro-82m"]);
    expect(calls[0]?.path).toBe("/desktop/audio/models?task=speak");
    await api.installRuntime(42023522);
    expect(calls[1]?.path).toBe("/desktop/audio/install");
    expect(calls[1]?.init?.body).toBe(JSON.stringify({ confirm_bytes: 42023522 }));
  });

  it("uploads a recording as a form and reads the engine's reason when it is refused", async () => {
    let status = 201;
    const { t, calls } = transport(() =>
      status === 201
        ? jsonRes({ id: "t1" }, 201)
        : jsonRes({ detail: { code: "needs_converter", message: "Install ffmpeg." } }, 422),
    );
    const api = createVoiceApi(t);
    const file = new File(["x"], "talk.wav", { type: "audio/wav" });
    await api.transcribe(file, "parakeet-tdt-0.6b-v3", "Call");
    const form = calls[0]?.init?.body as FormData;
    expect(form.get("model")).toBe("parakeet-tdt-0.6b-v3");
    expect(form.get("title")).toBe("Call");
    expect((form.get("file") as File).name).toBe("talk.wav");
    status = 422;
    await expect(api.transcribe(file)).rejects.toThrow("Install ffmpeg.");
  });

  it("treats deleting something already gone as done", async () => {
    const { t } = transport(() => new Response(null, { status: 404 }));
    const api = createVoiceApi(t);
    await expect(api.removeSpeech("x")).resolves.toBeUndefined();
    await expect(api.removeTranscript("x")).resolves.toBeUndefined();
  });
});

describe("saved voices", () => {
  it("sends a saved voice by id, and creates voices with the consent that was given", async () => {
    const r = runs([
      ev("done", {
        outputs: { status: "done", speech_id: "s", seconds: 1, audio_url: "u", sample_rate: 1 },
      }),
    ]);
    await makeSpeech(r, { text: "Hi", savedVoice: "v1", model: "m" }, new AbortController().signal);
    expect(r.seen.input).toEqual({ text: "Hi", model: "m", saved_voice: "v1" });

    const { t, calls } = transport(() => jsonRes({ id: "v1" }, 201));
    const api = createVoiceApi(t);
    await api.designVoice("Calm", "a deep, calm man");
    expect(calls[0]?.path).toBe("/products/wasifyai-voice/voices/design");
    expect(calls[0]?.init?.body).toBe(
      JSON.stringify({ name: "Calm", description: "a deep, calm man" }),
    );
    await api.cloneVoice(new File(["x"], "me.wav"), "Me", "permission", "the words");
    const form = calls[1]?.init?.body as FormData;
    expect([form.get("name"), form.get("consent"), form.get("reference_text")]).toEqual([
      "Me",
      "permission",
      "the words",
    ]);
    await api.voices("clone");
    expect(calls[2]?.path).toBe("/products/wasifyai-voice/voices?kind=clone");
  });
});
