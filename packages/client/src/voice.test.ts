import { describe, expect, it } from "vitest";
import type { ParsedEvent } from "./sse";
import type { Transport } from "./transport";
import { createVoiceApi, makeEdit, makeLyrics, makeSpeech, makeTrack } from "./voice";

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

describe("music", () => {
  it("sends only what was chosen, with the music task", async () => {
    const r = runs([
      ev("done", {
        outputs: { status: "done", track_id: "t1", title: "Summer", seconds: 30, audio_url: "u" },
      }),
    ]);
    const out = await makeTrack(
      r,
      {
        description: "pop, upbeat",
        model: "m",
        lyrics: "la la",
        duration: 45,
        seed: 3,
        instrumental: false,
      },
      new AbortController().signal,
    );
    expect(r.seen.input).toEqual({
      task: "music",
      text: "pop, upbeat",
      model: "m",
      lyrics: "la la",
      duration: 45,
      seed: 3,
    });
    expect(out).toEqual({
      ok: true,
      track: { id: "t1", title: "Summer", seconds: 30, audio_url: "u" },
    });
    const refused = await makeTrack(
      runs([
        ev("done", {
          outputs: {
            status: "refused",
            refusal: { code: "no_lyrics", message: "No lyrics here." },
          },
        }),
      ]),
      { description: "calm", mode: "sfx", lyrics: "words" },
      new AbortController().signal,
    );
    expect(refused).toEqual({ ok: false, code: "no_lyrics", message: "No lyrics here." });
  });

  it("lists, renames, deletes and downloads tracks", async () => {
    const { t, calls } = transport(() => jsonRes({ items: [{ id: "t1" }] }));
    const api = createVoiceApi(t);
    expect((await api.tracks()).map((x) => x.id)).toEqual(["t1"]);
    await api.renameTrack("t1", "Winter");
    expect(calls[1]?.path).toBe("/products/wasifyai-voice/tracks/t1");
    expect(calls[1]?.init?.body).toBe(JSON.stringify({ title: "Winter" }));
    await api.removeTrack("t1");
    expect(calls[2]?.init?.method).toBe("DELETE");
  });
});

describe("changing music and writing lyrics", () => {
  it("sends an edit with only the parts that were given", async () => {
    const r = runs([
      ev("done", {
        outputs: {
          status: "done",
          track_id: "t2",
          title: "Summer (repaint)",
          seconds: 20,
          audio_url: "u",
        },
      }),
    ]);
    const out = await makeEdit(
      r,
      {
        source: "t1",
        action: "repaint",
        description: "a drum fill",
        ranges: [[5, 10]],
        strength: 0.7,
        seed: 3,
      },
      new AbortController().signal,
    );
    expect(r.seen.input).toEqual({
      task: "music_edit",
      source_track: "t1",
      edit_action: "repaint",
      text: "a drum fill",
      edit_ranges: [[5, 10]],
      strength: 0.7,
      seed: 3,
    });
    expect(out.ok && out.track.id).toBe("t2");
    const ext = runs([
      ev("done", {
        outputs: { status: "refused", refusal: { code: "x", message: "Say how many seconds." } },
      }),
    ]);
    const refused = await makeEdit(
      ext,
      { source: "t1", action: "extend", description: "go on", extend: 10 },
      new AbortController().signal,
    );
    expect(ext.seen.input).toMatchObject({ extend_s: 10 });
    expect(refused).toEqual({ ok: false, code: "x", message: "Say how many seconds." });
  });

  it("streams lyrics as they are written and returns the cleaned words", async () => {
    const r = runs([
      ev("token", { text: "[verse]\n" }),
      ev("token", { text: "la la" }),
      ev("done", { outputs: { status: "done", lyrics: "[verse]\nla la la la" } }),
    ]);
    const seen: string[] = [];
    const out = await makeLyrics(
      r,
      { idea: "a summer day", style: "pop", duration: 60 },
      new AbortController().signal,
      (t) => seen.push(t),
    );
    expect(r.seen.input).toEqual({
      task: "lyrics",
      text: "a summer day",
      style: "pop",
      duration: 60,
    });
    expect(seen).toEqual(["[verse]\n", "[verse]\nla la"]);
    expect(out).toEqual({ ok: true, lyrics: "[verse]\nla la la la" });
    const failed = await makeLyrics(
      runs([ev("error", { code: "no_language_model", message: "Choose a chat model." })]),
      { idea: "x y z" },
      new AbortController().signal,
    );
    expect(failed).toEqual({
      ok: false,
      code: "no_language_model",
      message: "Choose a chat model.",
    });
  });

  it("marks favourites, lists them, and asks for the formats and the format of a download", async () => {
    const { t, calls } = transport((p) =>
      p.endsWith("/formats")
        ? jsonRes({ formats: ["wav", "m4a"] })
        : jsonRes({ items: [], id: "t1" }),
    );
    const api = createVoiceApi(t);
    await api.updateTrack("t1", { favourite: true });
    expect(calls[0]?.init?.body).toBe(JSON.stringify({ favourite: true }));
    await api.tracks({ favourites: true, limit: 10 });
    expect(calls[1]?.path).toBe("/products/wasifyai-voice/tracks?limit=10&favourites=true");
    expect(await api.formats()).toEqual(["wav", "m4a"]);
    await api.downloadTrack("t1", "m4a").catch(() => undefined);
    expect(calls[3]?.path).toBe("/products/wasifyai-voice/tracks/t1/download?format=m4a");
  });
});
