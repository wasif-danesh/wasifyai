// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  AudioRuntime,
  ParsedEvent,
  SavedVoice,
  Speech,
  Transcript,
  VoiceApi,
  VoiceModelInfo,
} from "@wasifyai/client";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { SaveAsProvider } from "../save";
import { MusicWorkspace } from "./MusicWorkspace";
import { SpeakWorkspace } from "./SpeakWorkspace";
import { TrackList } from "./TrackList";
import { TranscribeWorkspace } from "./TranscribeWorkspace";
import { VoicesWorkspace } from "./VoicesWorkspace";
import { modelOption, pickModel } from "./format";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

const model = (over: Partial<VoiceModelInfo> = {}): VoiceModelInfo => ({
  id: "kokoro-82m",
  title: "Kokoro 82M",
  licence: "Apache-2.0",
  engine: "audiocpp",
  family: "kokoro_tts",
  tasks: ["speak"],
  recommended: ["speak"],
  languages: ["en-us"],
  sample_rate: 24000,
  commercial_use: "yes",
  licence_evidence: "https://huggingface.co/hexgrad/Kokoro-82M",
  reviewed: "2026-10-16",
  measured: { platform: "darwin-arm64", speed_x: 8.6, memory_gb: 0.9, load_s: 4.7 },
  voices: [
    { id: "af_heart", label: "Heart", language: "en-us", gender: "female" },
    { id: "bm_george", label: "George", language: "en-gb", gender: "male" },
  ],
  default_voice: "af_heart",
  music: {},
  options: [
    {
      name: "speed",
      type: "float",
      label: "Speed",
      description: "How fast.",
      default: 1,
      min: 0.5,
      max: 2,
      values: [],
    },
  ],
  state: "ready",
  files_ready: true,
  runtime_ready: true,
  bytes_missing: 0,
  ...over,
});

const runtime = (over: Partial<AudioRuntime> = {}): AudioRuntime => ({
  installed: true,
  tag: "v0.9.0",
  backend: "metal",
  source: "managed",
  running: false,
  plan: {
    supported: true,
    platform: "darwin-arm64",
    tag: "v0.9.0",
    bytes: 42_023_522,
    url: "https://x",
    backend: "metal",
    measured: true,
    found: null,
  },
  install: { state: "idle", step: null, message: "", done_bytes: 0, total_bytes: 0 },
  ...over,
});

const speech = (over: Partial<Speech> = {}): Speech => ({
  id: "s1",
  mode: "speak",
  saved_voice_id: null,
  text: "Hello there",
  model_id: "kokoro-82m",
  voice: "af_heart",
  options: {},
  seconds: 65,
  sample_rate: 24000,
  load_s: 0,
  elapsed_s: 1,
  created_at: "2026-10-16T10:00:00Z",
  audio_url: "http://127.0.0.1/a.wav",
  ...over,
});

function api(over: Partial<Record<keyof VoiceApi, unknown>> = {}): VoiceApi {
  return {
    runtime: vi.fn(async () => runtime()),
    models: vi.fn(async () => [model()]),
    installRuntime: vi.fn(async () => runtime()),
    useFoundRuntime: vi.fn(async () => runtime()),
    stopRuntime: vi.fn(async () => ({ stopped: true })),
    voices: vi.fn(async () => []),
    designVoice: vi.fn(),
    cloneVoice: vi.fn(),
    updateVoice: vi.fn(),
    removeVoice: vi.fn(async () => undefined),
    speeches: vi.fn(async () => []),
    speech: vi.fn(),
    removeSpeech: vi.fn(async () => undefined),
    tracks: vi.fn(async () => []),
    track: vi.fn(),
    updateTrack: vi.fn(),
    formats: vi.fn(async () => ["wav"]),
    renameTrack: vi.fn(),
    removeTrack: vi.fn(async () => undefined),
    downloadTrack: vi.fn(async () => new Blob(["x"])),
    downloadSpeech: vi.fn(async () => new Blob(["x"])),
    transcripts: vi.fn(async () => []),
    transcript: vi.fn(),
    transcribe: vi.fn(),
    renameTranscript: vi.fn(),
    removeTranscript: vi.fn(async () => undefined),
    exportTranscript: vi.fn(async () => new Blob(["x"])),
    ...over,
  } as unknown as VoiceApi;
}

const runsThat = (events: ParsedEvent[]) => ({
  startRun: vi.fn(async (_p: string, _i: object, _s: AbortSignal, on: (e: ParsedEvent) => void) => {
    for (const e of events) on(e);
  }),
});

const done = ev("done", {
  outputs: {
    status: "done",
    speech_id: "s2",
    seconds: 3,
    audio_url: "http://x",
    sample_rate: 24000,
  },
});

describe("the model list", () => {
  it("names the recommended model, and says what a model that cannot be used yet needs", () => {
    const a = model();
    const b = model({ id: "vox", title: "VoxCPM2", recommended: [], state: "can_install" });
    const c = model({ id: "nc", title: "NC", recommended: [], commercial_use: "no" });
    expect(modelOption(a, "speak")).toBe("Kokoro 82M (recommended)");
    expect(modelOption(b, "speak")).toBe("VoxCPM2 (not on this computer yet)");
    expect(modelOption(c, "speak")).toBe("NC (not for commercial use)");
    expect(pickModel([b, a], "speak")?.id).toBe("kokoro-82m");
    expect(pickModel([b, a], "speak", "vox")?.id).toBe("vox");
    expect(pickModel([], "speak")).toBeNull();
  });
});

// Radix's pointer handling and the media element need these in jsdom
beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
  window.HTMLMediaElement.prototype.play = vi.fn(async () => {});
  window.HTMLMediaElement.prototype.pause = vi.fn();
});

const stage = () => screen.getByRole("region", { name: "Result" });

describe("text to speech", () => {
  it("speaks with the chosen voice and option, then plays it on the stage", async () => {
    const speeches = vi
      .fn()
      .mockResolvedValueOnce([])
      .mockResolvedValue([speech({ id: "s2", text: "Good morning", seconds: 3 })]);
    const runs = runsThat([ev("node", { label: "Making the speech" }), done]);
    const user = userEvent.setup();
    render(<SpeakWorkspace api={api({ speeches })} runs={runs} />);
    expect(await screen.findByRole("combobox", { name: "Model" })).toHaveTextContent("Kokoro 82M");
    const voices = screen.getByRole("group", { name: "Voices" });
    expect(within(voices).getAllByRole("radio")).toHaveLength(2);
    expect(within(voices).getByRole("radio", { name: /Heart/ })).toBeChecked(); // the model's own default
    await user.click(within(voices).getByRole("radio", { name: /George/ }));
    await user.click(screen.getByText("For experts"));
    fireEvent.keyDown(screen.getByRole("slider", { name: "Speed" }), { key: "ArrowRight" });
    await user.type(screen.getByLabelText("What should it say?"), "Good morning");
    await user.click(screen.getByRole("button", { name: "Make the speech" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[0]).toBe("wasifyai-voice");
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      text: "Good morning",
      model: "kokoro-82m",
      voice: "bm_george",
      options: { speed: 1.05 },
    });
    await waitFor(() => expect(stage()).toHaveAttribute("data-state", "result"));
    expect(within(stage()).getByText("Good morning")).toBeInTheDocument();
    expect(within(stage()).getByRole("button", { name: /Play Good morning/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open: Good morning" })).toBeInTheDocument(); // the recent strip
  });

  it("shows a refusal in words and keeps the text", async () => {
    const runs = runsThat([
      ev("done", {
        outputs: { status: "refused", refusal: { code: "x", message: "No such voice." } },
      }),
    ]);
    const user = userEvent.setup();
    render(<SpeakWorkspace api={api()} runs={runs} />);
    await user.type(await screen.findByLabelText("What should it say?"), "Hi");
    await user.click(screen.getByRole("button", { name: "Make the speech" }));
    expect(await screen.findByText("No such voice.")).toBeInTheDocument();
    expect(screen.getByLabelText("What should it say?")).toHaveValue("Hi");
  });

  it("will not speak with a model that is not ready, and offers the way to get it", async () => {
    const onGet = vi.fn();
    const models = vi.fn(async () => [model({ state: "can_install", bytes_missing: 189_549_408 })]);
    const user = userEvent.setup();
    render(<SpeakWorkspace api={api({ models })} runs={runsThat([])} onGetModel={onGet} />);
    await user.type(await screen.findByLabelText("What should it say?"), "Hi");
    expect(screen.getByRole("button", { name: "Make the speech" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Get it in the Model hub" }));
    expect(onGet).toHaveBeenCalledWith("kokoro-82m");
    expect(screen.getByText(/190 MB/)).toBeInTheDocument();
  });

  it("warns plainly about a model that is not for commercial use", async () => {
    const models = vi.fn(async () => [model({ commercial_use: "no", recommended: [] })]);
    render(<SpeakWorkspace api={api({ models })} runs={runsThat([])} />);
    expect(await screen.findByText("Not for commercial use")).toBeInTheDocument();
  });

  it("plays a voice heard before, and makes a sample of one never heard", async () => {
    const runs = runsThat([done]);
    const user = userEvent.setup();
    render(
      <SpeakWorkspace
        api={api({ speeches: vi.fn(async () => [speech({ voice: "af_heart" })]) })}
        runs={runs}
      />,
    );
    expect(await screen.findByRole("button", { name: "Play Heart" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hear a sample of George" }));
    expect(runs.startRun.mock.calls[0]?.[1]).toMatchObject({
      voice: "bm_george",
      model: "kokoro-82m",
    });
    expect(await screen.findByRole("button", { name: "Stop George" })).toBeInTheDocument();
  });

  it("opens a speech from the recent strip, and deletes it after asking", async () => {
    const removeSpeech = vi.fn(async () => undefined);
    const onTool = vi.fn();
    const user = userEvent.setup();
    render(
      <SpeakWorkspace
        api={api({ speeches: vi.fn(async () => [speech()]), removeSpeech })}
        runs={runsThat([])}
        onTool={onTool}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Open: Hello there" }));
    expect(within(stage()).getByText("Hello there")).toBeInTheDocument();
    expect(within(stage()).getAllByText(/1:05/).length).toBeGreaterThan(0);
    await user.click(within(stage()).getByRole("button", { name: /Change the voice/ }));
    expect(onTool).toHaveBeenCalledWith(expect.objectContaining({ id: "s1" }), "convert");
    await user.click(within(stage()).getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: /Delete/ }));
    expect(removeSpeech).not.toHaveBeenCalled(); // asks first
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(removeSpeech).toHaveBeenCalledWith("s1");
    await waitFor(() => expect(stage()).toHaveAttribute("data-state", "empty"));
  });

  it("makes a voice without leaving the screen, and speaks with it", async () => {
    const voices = vi
      .fn()
      .mockResolvedValueOnce([])
      .mockResolvedValue([saved({ id: "v9", name: "Calm" })]);
    const user = userEvent.setup();
    render(<SpeakWorkspace api={api({ voices })} runs={runsThat([])} />);
    await user.click(await screen.findByRole("button", { name: "Make a voice" }));
    expect(await screen.findByRole("dialog", { name: "Make a voice" })).toBeInTheDocument();
  });
});

describe("setting up the speech runtime", () => {
  it("says the size, asks, and downloads only on the second click", async () => {
    const installRuntime = vi.fn(async () => runtime());
    const rt = runtime({ installed: false });
    const models = vi.fn(async () => [model({ state: "needs_runtime", runtime_ready: false })]);
    const user = userEvent.setup();
    render(
      <SpeakWorkspace
        api={api({ runtime: vi.fn(async () => rt), models, installRuntime })}
        runs={runsThat([])}
      />,
    );
    await user.click(await screen.findByRole("button", { name: /Set up speech \(42 MB\)/ }));
    expect(installRuntime).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(installRuntime).toHaveBeenCalledWith(42_023_522);
  });

  it("offers a copy already on the computer, and says when the runtime is untested here", async () => {
    const useFoundRuntime = vi.fn(async () => runtime());
    const rt = runtime({
      installed: false,
      plan: { ...runtime().plan, measured: false, found: { path: "/x", tag: "v", backend: "cpu" } },
    });
    const user = userEvent.setup();
    render(
      <SpeakWorkspace
        api={api({ runtime: vi.fn(async () => rt), useFoundRuntime })}
        runs={runsThat([])}
      />,
    );
    expect(
      await screen.findByText(/has not been tested on this kind of computer/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use the copy already on this computer" }));
    expect(useFoundRuntime).toHaveBeenCalled();
  });
});

const transcript = (over: Partial<Transcript> = {}): Transcript => ({
  id: "t1",
  title: "Board meeting",
  source_name: "board.wav",
  model_id: "parakeet-tdt-0.6b-v3",
  text: "Hello there. Second sentence.",
  segments: [
    { start: 0, end: 1, text: "Hello there." },
    { start: 65, end: 67, text: "Second sentence." },
  ],
  seconds: 67,
  elapsed_s: 0.5,
  created_at: "2026-10-16T10:00:00Z",
  updated_at: "2026-10-16T10:00:00Z",
  ...over,
});

const asr = () =>
  model({
    id: "parakeet-tdt-0.6b-v3",
    title: "Parakeet TDT 0.6B v3",
    tasks: ["transcribe"],
    recommended: ["transcribe"],
    voices: [],
    default_voice: null,
    options: [],
  });

describe("speech to text", () => {
  it("transcribes a chosen recording with the chosen model and shows the times on the stage", async () => {
    const transcribe = vi.fn(async () => transcript());
    const user = userEvent.setup();
    render(<TranscribeWorkspace api={api({ models: vi.fn(async () => [asr()]), transcribe })} />);
    const input = (await screen.findByLabelText("Choose a recording")) as HTMLInputElement;
    await user.upload(input, new File(["x"], "board.wav", { type: "audio/wav" }));
    expect(screen.getByText("board.wav")).toBeInTheDocument(); // chosen, not sent yet
    expect(transcribe).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(transcribe).toHaveBeenCalled());
    const call = transcribe.mock.calls[0] as unknown as [File, string];
    expect(call[0].name).toBe("board.wav");
    expect(call[1]).toBe("parakeet-tdt-0.6b-v3");
    const article = await screen.findByRole("article", { name: "Transcript" });
    expect(within(article).getByText("1:05")).toBeInTheDocument();
    expect(within(article).getByText("Second sentence.")).toBeInTheDocument();
  });

  it("saves a transcript as subtitles", async () => {
    const exportTranscript = vi.fn(async () => new Blob(["1\n00:00"]));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const user = userEvent.setup();
    render(
      <TranscribeWorkspace
        api={api({
          models: vi.fn(async () => [asr()]),
          transcripts: vi.fn(async () => [transcript({ segments: [] })]),
          transcript: vi.fn(async () => transcript()),
          exportTranscript,
        })}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Open: Board meeting" }));
    await user.click(await screen.findByRole("button", { name: "Save .srt" }));
    expect(exportTranscript).toHaveBeenCalledWith("t1", "srt");
  });

  it("in the app window asks where to save a transcript and writes it there, or does nothing on cancel", async () => {
    const exportTranscript = vi.fn(async () => new Blob(["1\n00:00"]));
    const write = vi.fn(async (path: string) => ({ name: "board-meeting.txt", path }));
    const choose = vi.fn<(name: string) => Promise<string | null>>(
      async () => "/Users/me/Documents/b.txt",
    );
    const user = userEvent.setup();
    render(
      <SaveAsProvider value={{ choose, write }}>
        <TranscribeWorkspace
          api={api({
            models: vi.fn(async () => [asr()]),
            transcripts: vi.fn(async () => [transcript({ segments: [] })]),
            transcript: vi.fn(async () => transcript()),
            exportTranscript,
          })}
        />
      </SaveAsProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Open: Board meeting" }));
    await user.click(await screen.findByRole("button", { name: "Save .txt" }));
    expect(choose).toHaveBeenCalledWith("board-meeting.txt");
    await waitFor(() =>
      expect(write).toHaveBeenCalledWith("/Users/me/Documents/b.txt", expect.any(Blob)),
    );
    choose.mockResolvedValueOnce(null); // the person cancels the box: nothing is fetched or written
    exportTranscript.mockClear();
    write.mockClear();
    await user.click(screen.getByRole("button", { name: "Save .txt" }));
    await new Promise((r) => setTimeout(r, 20));
    expect(exportTranscript).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
  });

  it("says why a recording could not be read", async () => {
    const transcribe = vi.fn(async () => {
      throw new Error("This file is not a WAV. Install ffmpeg to use other formats.");
    });
    const user = userEvent.setup();
    render(<TranscribeWorkspace api={api({ models: vi.fn(async () => [asr()]), transcribe })} />);
    await user.upload(await screen.findByLabelText("Choose a recording"), new File(["x"], "a.mp3"));
    await user.click(screen.getByRole("button", { name: "Transcribe" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Install ffmpeg");
  });

  it("does not transcribe until the model is ready", async () => {
    const models = vi.fn(async () => [{ ...asr(), state: "can_install" as const }]);
    const user = userEvent.setup();
    render(<TranscribeWorkspace api={api({ models })} />);
    await user.upload(await screen.findByLabelText("Choose a recording"), new File(["x"], "a.wav"));
    expect(screen.getByRole("button", { name: "Transcribe" })).toBeDisabled();
  });
});

const saved = (over: Partial<SavedVoice> = {}): SavedVoice => ({
  id: "v1",
  name: "Calm",
  kind: "design",
  description: "a deep, calm man",
  reference_text: "",
  reference_seconds: null,
  consent: {},
  created_at: "2026-10-16T10:00:00Z",
  updated_at: "2026-10-16T10:00:00Z",
  ...over,
});

describe("your own voices", () => {
  it("saves a described voice", async () => {
    const designVoice = vi.fn(async () => saved());
    const voices = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([saved()]);
    const user = userEvent.setup();
    render(<VoicesWorkspace api={api({ voices, designVoice })} runs={runsThat([])} />);
    const save = await screen.findByRole("button", { name: "Save voice" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Name"), " Calm ");
    await user.click(screen.getByRole("button", { name: /A deep, calm older man/ }));
    await user.click(save);
    expect(designVoice).toHaveBeenCalledWith(
      "Calm",
      "A deep, calm older man with a slow British accent",
    );
    expect(await screen.findByText("a deep, calm man")).toBeInTheDocument();
  });

  it("will not save a cloned voice until it is said whose voice it is", async () => {
    const cloneVoice = vi.fn(async () => saved({ kind: "clone" }));
    const user = userEvent.setup();
    render(<VoicesWorkspace api={api({ cloneVoice })} runs={runsThat([])} />);
    await user.click(await screen.findByRole("tab", { name: "Clone from a recording" }));
    await user.type(screen.getByLabelText("Name"), "Me");
    await user.upload(screen.getByLabelText(/A recording of the voice/), new File(["x"], "me.wav"));
    await user.type(screen.getByLabelText("What is said in the recording"), "the words I say");
    const save = screen.getByRole("button", { name: "Save voice" });
    expect(save).toBeDisabled();
    await user.click(
      screen.getByLabelText("I have the permission of the person whose voice this is."),
    );
    expect(save).toBeEnabled();
    await user.click(save);
    const call = cloneVoice.mock.calls[0] as unknown as [File, string, string, string];
    expect([call[0].name, call[1], call[2], call[3]]).toEqual([
      "me.wav",
      "Me",
      "permission",
      "the words I say",
    ]);
  });

  it("plays a sample of a voice, and passes on what the engine says when it cannot", async () => {
    const runs = runsThat([done]);
    const user = userEvent.setup();
    const { rerender } = render(
      <VoicesWorkspace api={api({ voices: vi.fn(async () => [saved()]) })} runs={runs} />,
    );
    await user.click(await screen.findByRole("button", { name: "Hear a sample" }));
    expect(runs.startRun.mock.calls[0]?.[1]).toMatchObject({ saved_voice: "v1" });
    expect(await screen.findByLabelText("Calm speaking")).toHaveAttribute("src", "http://x");
    const failing = runsThat([
      ev("error", { code: "model_missing", message: "Get it in the Model hub." }),
    ]);
    rerender(
      <VoicesWorkspace api={api({ voices: vi.fn(async () => [saved()]) })} runs={failing} />,
    );
    await user.click(await screen.findByRole("button", { name: "Hear a sample" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Get it in the Model hub.");
  });

  it("shows a cloned voice with its recording, its words and what was said about whose it is", async () => {
    const v = saved({
      kind: "clone",
      reference_text: "the words I say",
      reference_seconds: 65,
      reference_url: "http://x/ref.wav",
      consent: { basis: "own", statement: "This is my own voice." },
    });
    render(<VoicesWorkspace api={api({ voices: vi.fn(async () => [v]) })} runs={runsThat([])} />);
    expect(await screen.findByText("cloned, 1:05")).toBeInTheDocument();
    expect(screen.getByText(/the words I say/)).toBeInTheDocument();
    expect(screen.getByText("This is my own voice.")).toBeInTheDocument();
  });

  it("changes a recording's words in a box of the page, never with window.prompt", async () => {
    // the app window has no window.prompt: it answers nothing at once
    vi.stubGlobal("prompt", () => {
      throw new Error("window.prompt is not available in the app window");
    });
    const v = saved({ kind: "clone", reference_text: "the words I say" });
    const updateVoice = vi.fn(async () => ({ ...v, reference_text: "what I really say" }));
    render(
      <VoicesWorkspace
        api={api({ voices: vi.fn(async () => [v]), updateVoice })}
        runs={runsThat([])}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Change the words" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(updateVoice).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Change the words" }));
    const field = screen.getByLabelText("The words spoken in the recording");
    expect(field).toHaveProperty("value", "the words I say");
    await userEvent.clear(field);
    await userEvent.type(field, "what I really say");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(updateVoice).toHaveBeenCalledWith("v1", { reference_text: "what I really say" });
    expect(await screen.findByText(/what I really say/)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

describe("text to speech with a saved voice", () => {
  it("lists the models that can do what the voice is, and speaks with the voice by id", async () => {
    const designer = model({
      id: "qwen3-tts-1.7b-voicedesign",
      title: "Qwen3-TTS 1.7B VoiceDesign",
      tasks: ["design"],
      recommended: ["design"],
      voices: [],
      default_voice: null,
      options: [],
    });
    const models = vi.fn(async (task?: string) => (task === "design" ? [designer] : [model()]));
    const runs = runsThat([done]);
    const user = userEvent.setup();
    render(
      <SpeakWorkspace
        api={api({ models, voices: vi.fn(async () => [saved()]) })}
        runs={runs}
        initialSavedVoice="v1"
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Model" })).toHaveTextContent(
        "Qwen3-TTS 1.7B VoiceDesign",
      ),
    );
    const voices = screen.getByRole("group", { name: "Voices" });
    expect(within(voices).getAllByRole("radio")).toHaveLength(1); // only the saved voice: no built-in ones
    expect(within(voices).getByRole("radio", { name: /Calm/ })).toBeChecked();
    await user.type(screen.getByLabelText("What should it say?"), "Good morning");
    await user.click(screen.getByRole("button", { name: "Make the speech" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      text: "Good morning",
      model: "qwen3-tts-1.7b-voicedesign",
      saved_voice: "v1",
    });
  });
});

const track = (over: Record<string, unknown> = {}) => ({
  id: "t1",
  title: "Summer",
  mode: "song" as "song" | "sfx" | "edit",
  favourite: false,
  parent_id: null,
  edit: {},
  description: "pop, upbeat",
  lyrics: "la la",
  instrumental: false,
  model_id: "ace-step-1.5-turbo",
  options: {},
  seed: 3,
  seconds: 31,
  sample_rate: 48000,
  load_s: 0,
  elapsed_s: 20,
  created_at: "2026-10-16T10:00:00Z",
  updated_at: "2026-10-16T10:00:00Z",
  audio_url: "http://x/t.wav",
  ...over,
});

const ace = () =>
  model({
    id: "ace-step-1.5-turbo",
    title: "ACE-Step 1.5 Turbo",
    tasks: ["music"],
    recommended: ["music"],
    voices: [],
    default_voice: null,
    options: [],
    measured: { platform: "darwin-arm64", speed_x: 2, memory_gb: 7, load_s: 5 },
    music: {
      modes: { song: { lyrics: "optional", instrumental: "toggle", duration: [5, 30, 240] } },
    },
  });
const stable = () =>
  model({
    id: "stable-audio-3-small-music",
    title: "Stable Audio 3 Small (music)",
    tasks: ["music"],
    recommended: [],
    commercial_use: "conditional",
    voices: [],
    default_voice: null,
    options: [],
    music: {
      modes: { song: { lyrics: "unused", instrumental: "always", duration: [1, 30, 120] } },
    },
  });

describe("music", () => {
  const doneTrack = ev("done", {
    outputs: {
      status: "done",
      track_id: "t2",
      title: "Summer",
      seconds: 30,
      audio_url: "http://x",
    },
  });

  it("asks only what the chosen model takes, makes the song and plays it on the stage", async () => {
    const models = vi.fn(async () => [ace(), stable()]);
    const tracks = vi
      .fn()
      .mockResolvedValueOnce([])
      .mockResolvedValue([track({ id: "t2", title: "Summer" })]);
    const runs = runsThat([ev("node", { label: "Making the music" }), doneTrack]);
    const user = userEvent.setup();
    render(<MusicWorkspace api={api({ models, tracks })} runs={runs} />);
    expect(await screen.findByRole("combobox", { name: "Model" })).toHaveTextContent(
      "ACE-Step 1.5 Turbo",
    );
    expect(screen.getByLabelText(/Lyrics \(optional\)/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /No singing/ })).toBeInTheDocument();
    expect(screen.getByText(/About 15 seconds of work/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Describe the song"), "upbeat");
    await user.click(screen.getByRole("button", { name: "pop" })); // a style chip adds its word
    expect(screen.getByLabelText("Describe the song")).toHaveValue("upbeat, pop");
    await user.type(screen.getByLabelText(/Lyrics \(optional\)/), "la la la");
    const length = screen.getByRole("slider", { name: "Length" });
    for (let i = 0; i < 15; i++) fireEvent.keyDown(length, { key: "ArrowRight" });
    await user.click(screen.getByRole("button", { name: "Make the song" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "music",
      text: "upbeat, pop",
      model: "ace-step-1.5-turbo",
      music_mode: "song",
      lyrics: "la la la",
      duration: 45,
    });
    await waitFor(() => expect(stage()).toHaveAttribute("data-state", "result"));
    expect(within(stage()).getByText("Summer")).toBeInTheDocument();
    expect(within(stage()).getByText("la la")).toBeInTheDocument(); // the lyrics under the player
  });

  it("hides the lyrics for a model that does not sing, and says what the model is", async () => {
    const models = vi.fn(async () => [ace(), stable()]);
    const user = userEvent.setup();
    render(<MusicWorkspace api={api({ models })} runs={runsThat([])} />);
    await user.click(await screen.findByRole("combobox", { name: "Model" }));
    await user.click(await screen.findByRole("option", { name: /Stable Audio 3 Small \(music\)/ }));
    expect(screen.queryByLabelText(/Lyrics/)).not.toBeInTheDocument();
    expect(screen.getByText("This model makes music without singing.")).toBeInTheDocument();
    expect(screen.getByText("Commercial use with conditions")).toBeInTheDocument();
  });

  it("leaves the singing out on request", async () => {
    const runs = runsThat([doneTrack]);
    const user = userEvent.setup();
    render(<MusicWorkspace api={api({ models: vi.fn(async () => [ace()]) })} runs={runs} />);
    await user.type(await screen.findByLabelText("Describe the song"), "calm piano");
    await user.click(screen.getByRole("checkbox", { name: /No singing/ }));
    expect(screen.queryByLabelText(/Lyrics/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Make the song" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toMatchObject({ instrumental: true });
    expect(runs.startRun.mock.calls[0]?.[1]).not.toHaveProperty("lyrics");
  });

  it("says why the music was not made", async () => {
    const runs = runsThat([
      ev("done", {
        outputs: { status: "refused", refusal: { code: "x", message: "ACE-Step needs lyrics." } },
      }),
    ]);
    const user = userEvent.setup();
    render(<MusicWorkspace api={api({ models: vi.fn(async () => [ace()]) })} runs={runs} />);
    await user.type(await screen.findByLabelText("Describe the song"), "calm piano");
    await user.click(screen.getByRole("button", { name: "Make the song" }));
    expect(await screen.findByText("ACE-Step needs lyrics.")).toBeInTheDocument();
  });

  it("opens the music made from the strip, renames and deletes it, asking first", async () => {
    const updateTrack = vi.fn(async () => track({ title: "Winter" }));
    const removeTrack = vi.fn(async () => undefined);
    const user = userEvent.setup();
    render(
      <MusicWorkspace
        api={api({
          models: vi.fn(async () => [ace()]),
          tracks: vi.fn(async () => [track()]),
          updateTrack,
          removeTrack,
        })}
        runs={runsThat([])}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Open: Summer" }));
    expect(within(stage()).getByText(/song · 0:31 · ACE-Step 1.5 Turbo/)).toBeInTheDocument();
    await user.click(within(stage()).getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const name = await screen.findByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Winter{Enter}");
    expect(updateTrack).toHaveBeenCalledWith("t1", { title: "Winter" });
    expect(await within(stage()).findByText("Winter")).toBeInTheDocument();
    await user.click(within(stage()).getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: /Delete/ }));
    expect(removeTrack).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(removeTrack).toHaveBeenCalledWith("t1");
  });
});

const aceEdit = () =>
  model({
    ...ace(),
    options: [
      {
        name: "bpm",
        type: "int",
        label: "Tempo",
        description: "",
        default: null,
        min: 30,
        max: 300,
        values: [],
      },
    ],
    music: {
      modes: {
        song: { lyrics: "optional", instrumental: "toggle", duration: [5, 30, 240] },
        edit: { actions: ["repaint", "extend", "cover"], max_ranges: 1, max_source_s: 240 },
      },
    },
  });

describe("more music", () => {
  it("makes several takes with the next seeds, and passes the model's own options", async () => {
    const runs = runsThat([
      ev("done", {
        outputs: { status: "done", track_id: "t", title: "x", seconds: 30, audio_url: "u" },
      }),
    ]);
    const user = userEvent.setup();
    render(<MusicWorkspace api={api({ models: vi.fn(async () => [aceEdit()]) })} runs={runs} />);
    await user.type(await screen.findByLabelText("Describe the song"), "upbeat pop");
    await user.click(screen.getByText("For experts"));
    fireEvent.change(screen.getByLabelText(/Tempo/), { target: { value: "96" } });
    await user.type(screen.getByLabelText(/Seed/), "10");
    await user.click(screen.getByRole("radio", { name: "3" }));
    await user.click(screen.getByRole("button", { name: "Make the song (3)" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalledTimes(3));
    const inputs = runs.startRun.mock.calls.map((c) => c[1] as Record<string, unknown>);
    expect(inputs.map((i) => i.seed)).toEqual([10, 11, 12]);
    expect(inputs[0]).toMatchObject({ options: { bpm: 96 }, task: "music" });
  });

  it("makes a track again with its own seed, or another take with a new one", async () => {
    const runs = runsThat([
      ev("done", {
        outputs: { status: "done", track_id: "t", title: "x", seconds: 31, audio_url: "u" },
      }),
    ]);
    const user = userEvent.setup();
    render(
      <MusicWorkspace
        api={api({
          models: vi.fn(async () => [aceEdit()]),
          tracks: vi.fn(async () => [track()]),
        })}
        runs={runs}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Open: Summer" }));
    await user.click(screen.getByRole("button", { name: "Make it again" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalledTimes(1));
    expect(runs.startRun.mock.calls[0]?.[1]).toMatchObject({
      text: "pop, upbeat",
      lyrics: "la la",
      seed: 3,
      duration: 31,
      model: "ace-step-1.5-turbo",
    });
    await user.click(await screen.findByRole("button", { name: "Open: Summer" }));
    await user.click(await screen.findByRole("button", { name: "Another take" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalledTimes(2));
    expect(runs.startRun.mock.calls[1]?.[1]).not.toHaveProperty("seed");
  });

  it("writes lyrics with the chat model and puts them in the form", async () => {
    const runs = runsThat([
      ev("token", { text: "[verse]\nsun" }),
      ev("done", { outputs: { status: "done", lyrics: "[verse]\nsun on the sea\nla la" } }),
    ]);
    const user = userEvent.setup();
    render(<MusicWorkspace api={api({ models: vi.fn(async () => [aceEdit()]) })} runs={runs} />);
    await user.type(await screen.findByLabelText("Describe the song"), "upbeat pop");
    await user.click(screen.getByRole("button", { name: "Write them for me" }));
    await user.type(screen.getByLabelText("What is the song about?"), "a summer day");
    await user.click(screen.getByRole("button", { name: "Write the lyrics" }));
    expect(await screen.findByLabelText(/The lyrics \(you can change them\)/)).toHaveValue(
      "[verse]\nsun on the sea\nla la",
    );
    expect(runs.startRun.mock.calls[0]?.[1]).toMatchObject({
      task: "lyrics",
      text: "a summer day",
      style: "upbeat pop",
      duration: 30,
    });
    await user.click(screen.getByRole("button", { name: "Use these lyrics" }));
    expect(screen.getByLabelText(/Lyrics \(optional\)/)).toHaveValue(
      "[verse]\nsun on the sea\nla la",
    );
  });

  it("says why lyrics could not be written", async () => {
    const runs = runsThat([
      ev("error", { code: "no_language_model", message: "Choose a chat model in Models." }),
    ]);
    const user = userEvent.setup();
    render(<MusicWorkspace api={api({ models: vi.fn(async () => [aceEdit()]) })} runs={runs} />);
    await user.click(await screen.findByRole("button", { name: "Write them for me" }));
    await user.type(screen.getByLabelText("What is the song about?"), "a summer day");
    await user.click(screen.getByRole("button", { name: "Write the lyrics" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a chat model in Models.");
  });

  it("changes a part of a track with the model that can, and adds the result to the list", async () => {
    const runs = runsThat([
      ev("done", {
        outputs: {
          status: "done",
          track_id: "t2",
          title: "Summer (repaint)",
          seconds: 31,
          audio_url: "u",
        },
      }),
    ]);
    const tracks = vi
      .fn()
      .mockResolvedValueOnce([track()])
      .mockResolvedValue([
        track(),
        track({ id: "t2", title: "Summer (repaint)", mode: "edit", edit: { action: "repaint" } }),
      ]);
    const user = userEvent.setup();
    render(
      <MusicWorkspace api={api({ models: vi.fn(async () => [aceEdit()]), tracks })} runs={runs} />,
    );
    await user.click(await screen.findByRole("button", { name: "Open: Summer" }));
    await user.click(within(stage()).getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: /Change a part/ }));
    const panel = await screen.findByRole("region", { name: "Change this music" });
    await user.type(within(panel).getByLabelText("What should it become?"), "a drum fill");
    fireEvent.change(within(panel).getByLabelText("Part 1 from"), { target: { value: "5" } });
    fireEvent.change(within(panel).getByLabelText("Part 1 to"), { target: { value: "10" } });
    await user.click(within(panel).getByRole("button", { name: "Change it" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "music_edit",
      source_track: "t1",
      edit_action: "repaint",
      text: "a drum fill",
      model: "ace-step-1.5-turbo",
      edit_ranges: [[5, 10]],
      strength: 0.6,
    });
    expect(await screen.findByText(/changed \(repaint\)/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Change this music" })).not.toBeInTheDocument();
  });

  it("offers an edit only the actions the model has, and says when no model can change a clip", async () => {
    const user = userEvent.setup();
    render(
      <MusicWorkspace
        api={api({ models: vi.fn(async () => [ace()]), tracks: vi.fn(async () => [track()]) })}
        runs={runsThat([])}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Open: Summer" }));
    await user.click(within(stage()).getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: /Change a part/ }));
    expect(
      await screen.findByText(/None of the music models on this computer can change a clip yet/),
    ).toBeInTheDocument();
  });

  it("hearts a track, finds music by its words, and saves in the formats this computer has", async () => {
    const updateTrack = vi.fn(async () => track({ favourite: true }));
    const downloadTrack = vi.fn(async () => new Blob(["x"]));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const list = [
      track(),
      track({ id: "t2", title: "Rain", description: "rain on a roof", lyrics: "" }),
    ];
    const user = userEvent.setup();
    render(
      <TrackList
        api={api({
          tracks: vi.fn(async () => list),
          updateTrack,
          formats: vi.fn(async () => ["wav", "m4a"]),
          downloadTrack,
        })}
        searchable
      />,
    );
    await screen.findByText("Summer");
    await user.type(screen.getByLabelText("Search your music"), "roof");
    expect(screen.queryByText("Summer")).not.toBeInTheDocument();
    expect(screen.getByText("Rain")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Search your music"));
    await user.click(
      screen.getAllByRole("button", { name: "Add to favourites" })[0] as HTMLElement,
    );
    expect(updateTrack).toHaveBeenCalledWith("t1", { favourite: true });
    await user.click(screen.getByLabelText("Favourites only"));
    expect(screen.queryByText("Rain")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save M4A" }));
    expect(downloadTrack).toHaveBeenCalledWith("t1", "m4a");
    expect(screen.queryByRole("button", { name: "Save MP3" })).not.toBeInTheDocument();
  });
});
