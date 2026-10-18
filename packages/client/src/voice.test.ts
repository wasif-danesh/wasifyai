import { describe, expect, it } from "vitest";
import type { ParsedEvent } from "./sse";
import type { Transport } from "./transport";
import {
  convertVoice,
  createVoiceApi,
  dubScript,
  editWords,
  makeAudiobook,
  makeClip,
  makeDub,
  makeEdit,
  makeLyrics,
  makeSpeech,
  makeTrack,
  separateAudio,
} from "./voice";

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

describe("the audio tools", () => {
  const done = (tracks: Record<string, unknown>[]) =>
    ev("done", { outputs: { status: "done", tracks } });

  it("splits a recording and returns every part that was kept", async () => {
    const r = runs([
      ev("node", { label: "Splitting" }),
      done([
        {
          track_id: "t1",
          title: "Song (vocals)",
          seconds: 20,
          audio_url: "http://x/1.wav",
          stem: "vocals",
        },
        {
          track_id: "t2",
          title: "Song (drums)",
          seconds: 20,
          audio_url: "http://x/2.wav",
          stem: "drums",
        },
      ]),
    ]);
    const steps: string[] = [];
    const out = await separateAudio(
      r,
      { source: { kind: "track", id: "src" }, model: "htdemucs", stems: ["vocals", "drums"] },
      new AbortController().signal,
      (l) => steps.push(l),
    );
    expect(r.seen.input).toEqual({
      task: "separate",
      source_track: "src",
      model: "htdemucs",
      stems: ["vocals", "drums"],
    });
    expect(steps).toEqual(["Splitting"]);
    expect(out.ok && out.tracks.map((t) => t.stem)).toEqual(["vocals", "drums"]);
  });

  it("points a run at a speech or a track and sends only what was chosen", async () => {
    const r = runs([done([{ track_id: "t1", title: "x", seconds: 1, audio_url: "u" }])]);
    await separateAudio(r, { source: { kind: "speech", id: "sp" } }, new AbortController().signal);
    expect(r.seen.input).toEqual({ task: "separate", source_speech: "sp" });
    const c = runs([done([{ track_id: "t1", title: "x", seconds: 1, audio_url: "u" }])]);
    await convertVoice(
      c,
      {
        source: { kind: "track", id: "a" },
        voice: "v1",
        model: "meanvc2",
        seed: 3,
        title: " As Ann ",
      },
      new AbortController().signal,
    );
    expect(c.seen.input).toEqual({
      task: "convert",
      source_track: "a",
      saved_voice: "v1",
      model: "meanvc2",
      seed: 3,
      title: " As Ann ",
    });
    const e = runs([done([{ track_id: "t1", title: "x", seconds: 1, audio_url: "u" }])]);
    await editWords(
      e,
      {
        source: { kind: "track", id: "a" },
        oldText: "Hello brave",
        newText: "Hello small",
        model: "dots-tts-edit",
      },
      new AbortController().signal,
    );
    expect(e.seen.input).toEqual({
      task: "speech_edit",
      source_track: "a",
      old_text: "Hello brave",
      text: "Hello small",
      model: "dots-tts-edit",
    });
  });

  it("says why in words when the engine refuses, fails, or the connection is lost", async () => {
    const refused = await convertVoice(
      runs([
        ev("done", {
          outputs: {
            status: "refused",
            refusal: { code: "voice_needs_recording", message: "Use a cloned voice." },
          },
        }),
      ]),
      { source: { kind: "track", id: "a" }, voice: "v" },
      new AbortController().signal,
    );
    expect(refused).toEqual({
      ok: false,
      code: "voice_needs_recording",
      message: "Use a cloned voice.",
    });
    const failed = await editWords(
      runs([ev("error", { code: "model_missing", message: "Get it in Models." })]),
      { source: { kind: "track", id: "a" }, oldText: "a", newText: "b" },
      new AbortController().signal,
    );
    expect(failed).toEqual({ ok: false, code: "model_missing", message: "Get it in Models." });
    const lost = await separateAudio(
      runs([]),
      { source: { kind: "track", id: "a" } },
      new AbortController().signal,
    );
    expect(!lost.ok && lost.code).toBe("lost");
  });

  it("adds a recording from this computer and writes down what one says", async () => {
    const { t, calls } = transport((path) =>
      path.endsWith("/words")
        ? jsonRes({ text: "Hello there", seconds: 2, model: "parakeet" })
        : jsonRes({ id: "t9", title: "Dad", mode: "imported" }, 201),
    );
    const api = createVoiceApi(t);
    const file = new File(["RIFF"], "dad.wav", { type: "audio/wav" });
    const track = await api.importTrack(file, "Dad");
    expect(track.mode).toBe("imported");
    expect(calls[0]?.path).toBe("/products/wasifyai-voice/tracks/import");
    expect(calls[0]?.init?.body).toBeInstanceOf(FormData);
    const words = await api.words({ kind: "speech", id: "s1" });
    expect(words.text).toBe("Hello there");
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({ kind: "speech", id: "s1" });
  });
});

describe("lip sync", () => {
  const made = ev("done", {
    outputs: {
      status: "done",
      clip_id: "c1",
      title: "Hello",
      seconds: 5.4,
      video_url: "http://x/c.mp4",
    },
  });

  it("sends the picture, what the person said about it and the voice, and returns the clip", async () => {
    const r = runs([ev("node", { label: "Making the video" }), made]);
    const steps: string[] = [];
    const out = await makeClip(
      r,
      {
        picture: "p1",
        pictureBasis: "drawn",
        voiceBasis: "own",
        source: { kind: "track", id: "t1" },
        model: "musetalk-v15",
        title: " Hi ",
      },
      new AbortController().signal,
      (l) => steps.push(l),
    );
    expect(r.seen.input).toEqual({
      task: "lipsync",
      picture: "p1",
      picture_basis: "drawn",
      voice_basis: "own",
      source_track: "t1",
      model: "musetalk-v15",
      title: " Hi ",
    });
    expect(steps).toEqual(["Making the video"]);
    expect(out).toEqual({
      ok: true,
      clip: { id: "c1", title: "Hello", seconds: 5.4, video_url: "http://x/c.mp4" },
    });
  });

  it("sends words instead of a recording, and never both", async () => {
    const r = runs([made]);
    await makeClip(
      r,
      {
        picture: "p1",
        pictureBasis: "own",
        voiceBasis: "generated",
        text: "Hello there",
        voice: "af_heart",
        source: { kind: "speech", id: "s1" },
      },
      new AbortController().signal,
    );
    expect(r.seen.input).toEqual({
      task: "lipsync",
      picture: "p1",
      picture_basis: "own",
      voice_basis: "generated",
      text: "Hello there",
      voice: "af_heart",
    });
  });

  it("says why in words when it is refused, fails, or the connection is lost", async () => {
    const base = {
      picture: "p",
      pictureBasis: "drawn",
      voiceBasis: "own",
      source: { kind: "track", id: "t" },
    } as const;
    const refused = await makeClip(
      runs([
        ev("done", {
          outputs: {
            status: "refused",
            refusal: { code: "consent_required", message: "Say whose voice." },
          },
        }),
      ]),
      base,
      new AbortController().signal,
    );
    expect(refused).toEqual({ ok: false, code: "consent_required", message: "Say whose voice." });
    const failed = await makeClip(
      runs([ev("error", { code: "no_face", message: "No clear face was found in the picture." })]),
      base,
      new AbortController().signal,
    );
    expect(failed).toEqual({
      ok: false,
      code: "no_face",
      message: "No clear face was found in the picture.",
    });
    const lost = await makeClip(runs([]), base, new AbortController().signal);
    expect(!lost.ok && lost.code).toBe("lost");
  });

  it("adds a picture, lists, renames, saves and removes clips, and sets the engine up", async () => {
    const { t, calls } = transport((path) =>
      path.endsWith("/pictures")
        ? jsonRes({ id: "p1", width: 300, height: 447, url: "http://x/p.png" }, 201)
        : path === "/desktop/lipsync"
          ? jsonRes({
              installed: false,
              plan: { supported: true, bytes: 1 },
              install: { state: "idle" },
            })
          : path.endsWith("/clips?limit=100")
            ? jsonRes({ items: [{ id: "c1", title: "Hello" }] })
            : jsonRes({ id: "c1", title: "Hi" }),
    );
    const api = createVoiceApi(t);
    const file = new File(["x"], "face.png", { type: "image/png" });
    expect((await api.addPicture(file)).id).toBe("p1");
    expect(calls[0]?.path).toBe("/products/wasifyai-voice/pictures");
    expect((await api.clips()).map((c) => c.id)).toEqual(["c1"]);
    expect((await api.lipsyncEngine()).installed).toBe(false);
    await api.updateClip("c1", { title: "Hi" });
    expect(calls.at(-1)?.path).toBe("/products/wasifyai-voice/clips/c1");
    expect(calls.at(-1)?.init?.method).toBe("PATCH");
    await api.installLipsyncEngine(1_500_000_000);
    expect(calls.at(-1)?.path).toBe("/desktop/lipsync/install");
    expect(JSON.parse(String(calls.at(-1)?.init?.body))).toEqual({ confirm_bytes: 1_500_000_000 });
  });
});

describe("dubbing", () => {
  const written = ev("done", {
    outputs: {
      status: "done",
      language: "es",
      seconds: 10.3,
      vocals_track: "v1",
      background_track: "b1",
      segments: [{ start: 0, end: 1.5, source: "Hello.", text: "Hola." }],
    },
  });

  it("asks for the script and returns the lines with the tracks it kept", async () => {
    const r = runs([ev("node", { label: "Translating" }), written]);
    const steps: string[] = [];
    const out = await dubScript(
      r,
      { source: { kind: "speech", id: "s1" }, language: "es", background: true },
      new AbortController().signal,
      (l) => steps.push(l),
    );
    expect(r.seen.input).toEqual({
      task: "dub_script",
      source_speech: "s1",
      language: "es",
      background: true,
    });
    expect(steps).toEqual(["Translating"]);
    expect(out).toEqual({
      ok: true,
      script: {
        segments: [{ start: 0, end: 1.5, source: "Hello.", text: "Hola." }],
        language: "es",
        seconds: 10.3,
        vocalsTrack: "v1",
        backgroundTrack: "b1",
      },
    });
  });

  it("sends the script as the person left it with the voice and what they said about it", async () => {
    const r = runs([
      ev("done", {
        outputs: {
          status: "done",
          track_id: "d1",
          title: "Hi (Spanish)",
          seconds: 11.9,
          audio_url: "http://x/d.wav",
          fit: { lines: 1, sped_up: 0, max_overflow_s: 0, elapsed_s: 3 },
        },
      }),
    ]);
    const out = await makeDub(
      r,
      {
        source: { kind: "track", id: "t1" },
        language: "es",
        segments: [{ start: 0, end: 1.5, source: "Hello.", text: "Hola, amigos." }],
        voiceFrom: "speaker",
        speakerBasis: "own",
        vocalsTrack: "v1",
        backgroundTrack: "b1",
        model: "qwen3-tts-0.6b-base",
      },
      new AbortController().signal,
    );
    expect(r.seen.input).toEqual({
      task: "dub",
      source_track: "t1",
      language: "es",
      segments: [{ start: 0, end: 1.5, source: "Hello.", text: "Hola, amigos." }],
      voice_from: "speaker",
      speaker_basis: "own",
      vocals_track: "v1",
      background_track: "b1",
      model: "qwen3-tts-0.6b-base",
    });
    expect(out.ok && out.track.id).toBe("d1");
    expect(out.ok && out.fit.lines).toBe(1);
  });

  it("says why in words when it is refused, fails, or the connection is lost", async () => {
    const asked = { source: { kind: "track", id: "t" }, language: "es" } as const;
    const refused = await makeDub(
      runs([
        ev("done", {
          outputs: {
            status: "refused",
            refusal: { code: "consent_required", message: "Say whose voice." },
          },
        }),
      ]),
      { ...asked, segments: [], voiceFrom: "speaker" },
      new AbortController().signal,
    );
    expect(refused).toEqual({ ok: false, code: "consent_required", message: "Say whose voice." });
    const failed = await dubScript(
      runs([
        ev("error", { code: "language_failed", message: "The language model did not answer." }),
      ]),
      asked,
      new AbortController().signal,
    );
    expect(failed).toEqual({
      ok: false,
      code: "language_failed",
      message: "The language model did not answer.",
    });
    const lost = await makeDub(
      runs([]),
      { ...asked, segments: [], voiceFrom: "builtin" },
      new AbortController().signal,
    );
    expect(!lost.ok && lost.code).toBe("lost");
  });
});

describe("audiobooks", () => {
  it("plans the chapters of a text without keeping anything", async () => {
    const { t, calls } = transport(() =>
      jsonRes({
        chapters: [{ title: "One", text: "Hi.", chars: 3, estimated_seconds: 1 }],
        chars: 3,
        estimated_seconds: 1,
      }),
    );
    const plan = await createVoiceApi(t).planBook("# One\nHi.", 3000);
    expect(plan.chapters[0]?.title).toBe("One");
    expect(calls[0]?.path).toBe("/products/wasifyai-voice/audiobook/plan");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ text: "# One\nHi.", target: 3000 });
  });

  it("sends the chapters as the person left them with the voice, and returns each kept chapter", async () => {
    const r = runs([
      ev("node", { label: "Chapter 1 of 2, part 1 of 3" }),
      ev("done", {
        outputs: {
          status: "done",
          seconds: 31.5,
          tracks: [
            {
              track_id: "c1",
              title: "B - 1. One",
              seconds: 19.6,
              audio_url: "http://x/1.wav",
              chapter: 1,
            },
            {
              track_id: "c2",
              title: "B - 2. Two",
              seconds: 11.9,
              audio_url: "http://x/2.wav",
              chapter: 2,
            },
          ],
          book: { track_id: "b", title: "B", seconds: 33, audio_url: "http://x/b.wav" },
        },
      }),
    ]);
    const steps: string[] = [];
    const out = await makeAudiobook(
      r,
      {
        title: "B",
        chapters: [
          { title: "One", text: "Hi." },
          { title: "Two", text: "Bye." },
        ],
        voice: "af_heart",
        model: "kokoro-82m",
        options: { speed: 1.1 },
        whole: true,
        readTitles: false,
      },
      new AbortController().signal,
      (l) => steps.push(l),
    );
    expect(r.seen.input).toEqual({
      task: "audiobook",
      title: "B",
      chapters: [
        { title: "One", text: "Hi." },
        { title: "Two", text: "Bye." },
      ],
      voice: "af_heart",
      model: "kokoro-82m",
      options: { speed: 1.1 },
      whole: true,
      read_titles: false,
    });
    expect(steps).toEqual(["Chapter 1 of 2, part 1 of 3"]);
    expect(out.ok && out.tracks.map((x) => x.chapter)).toEqual([1, 2]);
    expect(out.ok && out.book?.id).toBe("b");
  });

  it("says why in words when it is refused or fails, and that the chapters done are kept", async () => {
    const asked = { title: "B", chapters: [{ title: "One", text: "Hi." }] };
    const refused = await makeAudiobook(
      runs([
        ev("done", {
          outputs: {
            status: "refused",
            refusal: { code: "unknown_voice", message: "That saved voice is no longer there." },
          },
        }),
      ]),
      { ...asked, savedVoice: "x" },
      new AbortController().signal,
    );
    expect(refused).toEqual({
      ok: false,
      code: "unknown_voice",
      message: "That saved voice is no longer there.",
    });
    const failed = await makeAudiobook(
      runs([
        ev("error", {
          code: "engine_stopped",
          message: "The speech runtime stopped. Chapters 1 to 2 were kept in Your music.",
        }),
      ]),
      asked,
      new AbortController().signal,
    );
    expect(!failed.ok && failed.message).toContain("were kept in Your music");
    const lost = await makeAudiobook(runs([]), asked, new AbortController().signal);
    expect(!lost.ok && lost.code).toBe("lost");
  });
});

describe("a hosted deployment's voice api", () => {
  const answering = (calls: string[], body: unknown): Transport => ({
    async fetch(path) {
      calls.push(path);
      return new Response(JSON.stringify(body), {
        headers: { "content-type": "application/json" },
      });
    },
  });

  it("lists the product's models from the product, not from the window's engine", async () => {
    const calls: string[] = [];
    const api = createVoiceApi(answering(calls, { models: [{ id: "hosted-speech" }] }), {
      hosted: true,
    });
    expect((await api.models("speak")).map((m) => m.id)).toEqual(["hosted-speech"]);
    expect(calls).toEqual(["/products/wasifyai-voice/models?task=speak"]);
  });

  it("has nothing to set up when every model is hosted", async () => {
    const calls: string[] = [];
    const api = createVoiceApi(answering(calls, { hosted: true }), { hosted: true });
    expect((await api.runtime()).installed).toBe(true);
    expect(calls).toEqual(["/products/wasifyai-voice/runtime"]);
  });

  it("shows the state of a runtime the service has, and cannot set it up from the page", async () => {
    const calls: string[] = [];
    const api = createVoiceApi(answering(calls, { installed: false, install: { state: "idle" } }), {
      hosted: true,
    });
    expect((await api.runtime()).installed).toBe(false);
    await expect(api.installRuntime(1)).rejects.toThrow(/whoever runs this service/);
    await expect(api.stopRuntime()).rejects.toThrow(/whoever runs this service/);
    await expect(api.installLipsyncEngine(1)).rejects.toThrow(/whoever runs this service/);
    expect(calls).toEqual(["/products/wasifyai-voice/runtime"]);
  });

  it("reads the lip sync component from the product", async () => {
    const calls: string[] = [];
    const api = createVoiceApi(answering(calls, { installed: true }), { hosted: true });
    expect((await api.lipsyncEngine()).installed).toBe(true);
    expect(calls).toEqual(["/products/wasifyai-voice/lipsync-engine"]);
  });
});
