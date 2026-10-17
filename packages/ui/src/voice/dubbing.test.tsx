// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  ParsedEvent,
  SavedVoice,
  Speech,
  Track,
  VoiceApi,
  VoiceModelInfo,
} from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { DubbingWorkspace, SPEAKER_TEXT } from "./DubbingWorkspace";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

const base = {
  licence: "Apache-2.0",
  engine: "audiocpp",
  family: "x",
  sample_rate: 24000,
  commercial_use: "yes" as const,
  licence_evidence: "https://example.test",
  reviewed: "2026-10-16",
  measured: { platform: "darwin-arm64", speed_x: 3, memory_gb: null, load_s: null },
  default_voice: null,
  options: [],
  music: {},
  state: "ready" as const,
  files_ready: true,
  runtime_ready: true,
  bytes_missing: 0,
};

const kokoro = {
  ...base,
  id: "kokoro-82m",
  title: "Kokoro 82M",
  tasks: ["speak"],
  recommended: ["speak"],
  languages: ["en-us", "en-gb"],
  voices: [
    { id: "af_heart", label: "Heart", language: "en-us", gender: "female" },
    { id: "am_adam", label: "Adam", language: "en-us", gender: "male" },
  ],
} as unknown as VoiceModelInfo;
const qwen = {
  ...base,
  id: "qwen3-tts-0.6b-base",
  title: "Qwen3-TTS 0.6B",
  tasks: ["clone"],
  recommended: ["clone"],
  languages: ["zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"],
  voices: [],
} as unknown as VoiceModelInfo;

const track = (): Track =>
  ({
    id: "t1",
    title: "My talk",
    mode: "imported",
    seconds: 10,
    audio_url: "http://x/a.wav",
  }) as Track;
const speech = (): Speech =>
  ({ id: "s1", text: "Hello", seconds: 3, audio_url: "http://x/s.wav" }) as Speech;
const voice = (over: Partial<SavedVoice> = {}): SavedVoice =>
  ({ id: "v1", name: "Ann", kind: "clone", consent: { basis: "own" }, ...over }) as SavedVoice;

function api(over: Record<string, unknown> = {}): VoiceApi {
  return {
    runtime: vi.fn(async () => ({
      installed: true,
      install: { state: "idle", step: null, message: "", done_bytes: 0, total_bytes: 0 },
    })),
    models: vi.fn(async (task?: string) =>
      task === "speak" ? [kokoro] : task === "clone" ? [qwen] : [kokoro, qwen],
    ),
    tracks: vi.fn(async () => [track()]),
    speeches: vi.fn(async () => [speech()]),
    voices: vi.fn(async () => []),
    ...over,
  } as unknown as VoiceApi;
}

const runsFor = (script: ParsedEvent[], dub: ParsedEvent[] = []) => ({
  startRun: vi.fn(
    async (_p: string, input: object, _s: AbortSignal, on: (e: ParsedEvent) => void) => {
      const task = (input as { task?: string }).task;
      for (const e of task === "dub_script" ? script : dub) on(e);
    },
  ),
});

const scripted = ev("done", {
  outputs: {
    status: "done",
    language: "es",
    seconds: 10,
    vocals_track: "v-track",
    background_track: "b-track",
    segments: [
      { start: 0, end: 2, source: "Good evening.", text: "Buenas noches." },
      { start: 2.5, end: 6, source: "Thank you for coming.", text: "Gracias por venir." },
    ],
  },
});
const dubbed = ev("done", {
  outputs: {
    status: "done",
    track_id: "d1",
    title: "My talk (Spanish)",
    seconds: 10.3,
    audio_url: "http://x/d.wav",
    fit: { lines: 2, sped_up: 1, max_overflow_s: 0, elapsed_s: 5 },
  },
});

async function writeScript(language = "es") {
  await userEvent.selectOptions(await screen.findByLabelText("Which recording?"), "track:t1");
  await userEvent.selectOptions(screen.getByLabelText("Dub it into"), language);
  await userEvent.click(screen.getByRole("button", { name: "Write the script" }));
  await screen.findByLabelText("Line 1");
}

describe("dubbing a recording", () => {
  it("offers the languages some voice model speaks, and writes the script after separating the voice", async () => {
    const runs = runsFor([ev("node", { label: "Translating" }), scripted]);
    render(<DubbingWorkspace api={api()} runs={runs} />);
    const language = await screen.findByLabelText("Dub it into");
    const names = within(language)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(names).toContain("Spanish");
    expect(names).toContain("English");
    expect(names).not.toContain("Maltese");
    expect(
      (screen.getByRole("button", { name: "Write the script" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    await writeScript();
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "dub_script",
      source_track: "t1",
      language: "es",
      background: true,
    });
    expect((screen.getByLabelText("Line 2") as HTMLTextAreaElement).value).toBe(
      "Gracias por venir.",
    );
  });

  it("copies the speaker only with their word, and sends the script as it was changed", async () => {
    const runs = runsFor([scripted], [dubbed]);
    render(<DubbingWorkspace api={api()} runs={runs} />);
    await writeScript();
    const make = screen.getByRole("button", { name: "Make the dub" }) as HTMLButtonElement;
    expect(make.disabled).toBe(true); // the speaker's voice is the default and nobody said whose it is
    expect(screen.getByText(/Say whose voice it is to copy it/)).toBeTruthy();
    await userEvent.click(screen.getByRole("radio", { name: SPEAKER_TEXT.own }));
    const line = screen.getByLabelText("Line 1");
    await userEvent.clear(line);
    await userEvent.type(line, "Muy buenas noches.");
    expect(make.disabled).toBe(false);
    await userEvent.click(make);
    await waitFor(() => expect(runs.startRun).toHaveBeenCalledTimes(2));
    expect(runs.startRun.mock.calls[1]?.[1]).toEqual({
      task: "dub",
      source_track: "t1",
      language: "es",
      segments: [
        { start: 0, end: 2, source: "Good evening.", text: "Muy buenas noches." },
        { start: 2.5, end: 6, source: "Thank you for coming.", text: "Gracias por venir." },
      ],
      voice_from: "speaker",
      speaker_basis: "own",
      model: "qwen3-tts-0.6b-base",
      vocals_track: "v-track",
      background_track: "b-track",
    });
    const result = await screen.findByRole("region", { name: "The dub" });
    expect(result.textContent).toContain("My talk (Spanish)");
    expect(result.textContent).toContain("1 played a little faster");
  });

  it("cannot make a line empty, and can drop the background", async () => {
    const runs = runsFor([scripted], [dubbed]);
    render(<DubbingWorkspace api={api()} runs={runs} />);
    await userEvent.selectOptions(await screen.findByLabelText("Which recording?"), "speech:s1");
    await userEvent.click(screen.getByRole("checkbox", { name: /Keep the music/ }));
    await userEvent.selectOptions(screen.getByLabelText("Dub it into"), "es");
    await userEvent.click(screen.getByRole("button", { name: "Write the script" }));
    await screen.findByLabelText("Line 1");
    // the voice still has to be separated to be copied, even without the background
    expect(runs.startRun.mock.calls[0]?.[1]).toMatchObject({
      source_speech: "s1",
      background: true,
    });
    await userEvent.click(screen.getByRole("radio", { name: SPEAKER_TEXT.permission }));
    const make = screen.getByRole("button", { name: "Make the dub" }) as HTMLButtonElement;
    expect(make.disabled).toBe(false);
    await userEvent.clear(screen.getByLabelText("Line 2"));
    expect(make.disabled).toBe(true);
    await userEvent.type(screen.getByLabelText("Line 2"), "Gracias.");
    await userEvent.click(make);
    await waitFor(() => expect(runs.startRun).toHaveBeenCalledTimes(2));
    const sent = runs.startRun.mock.calls[1]?.[1] as Record<string, unknown>;
    expect(sent.speaker_basis).toBe("permission");
    expect(sent.background_track).toBeUndefined();
  });

  it("uses a saved voice or a built-in one, each with the model that does it", async () => {
    const runs = runsFor(
      [
        ev("done", {
          outputs: {
            ...scripted.data,
            status: "done",
            language: "en",
            segments: [{ start: 0, end: 2, source: "Buenas.", text: "Good evening." }],
          },
        }),
      ],
      [dubbed],
    );
    const a = api({
      voices: vi.fn(async () => [voice(), voice({ id: "v2", name: "Design", kind: "design" })]),
    });
    render(<DubbingWorkspace api={a} runs={runs} />);
    await writeScript("en");
    await userEvent.click(screen.getByRole("radio", { name: "A voice I saved" }));
    const make = screen.getByRole("button", { name: "Make the dub" }) as HTMLButtonElement;
    expect(make.disabled).toBe(true);
    const saved = screen.getByLabelText("Saved voice");
    expect(within(saved).queryByRole("option", { name: "Design" })).toBeNull(); // no recording to copy
    await userEvent.selectOptions(saved, "v1");
    expect(make.disabled).toBe(false);
    await userEvent.click(screen.getByRole("radio", { name: /A built-in voice/ }));
    await userEvent.selectOptions(screen.getByLabelText("Built-in voice"), "am_adam");
    expect(make.disabled).toBe(false);
    await userEvent.click(make);
    await waitFor(() => expect(runs.startRun).toHaveBeenCalledTimes(2));
    expect(runs.startRun.mock.calls[1]?.[1]).toMatchObject({
      voice_from: "builtin",
      voice: "am_adam",
      model: "kokoro-82m",
    });
  });

  it("says in words why a script or a dub was not made", async () => {
    const failing = runsFor([
      ev("error", {
        code: "language_failed",
        message: "The language model did not answer. Check it in Models and try again.",
      }),
    ]);
    render(<DubbingWorkspace api={api()} runs={failing} />);
    await userEvent.selectOptions(await screen.findByLabelText("Which recording?"), "track:t1");
    await userEvent.selectOptions(screen.getByLabelText("Dub it into"), "es");
    await userEvent.click(screen.getByRole("button", { name: "Write the script" }));
    expect((await screen.findByRole("alert")).textContent).toContain("language model");
  });

  it("says when no model speaks the language the voice is wanted in", async () => {
    const onlyKokoro = api({
      models: vi.fn(async (task?: string) => (task === "clone" ? [] : [kokoro])),
    });
    render(<DubbingWorkspace api={onlyKokoro} runs={runsFor([scripted])} />);
    const language = await screen.findByLabelText("Dub it into");
    expect(within(language).queryByRole("option", { name: "Spanish" })).toBeNull();
    expect(within(language).getByRole("option", { name: "English" })).toBeTruthy();
  });
});
