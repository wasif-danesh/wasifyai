// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  AudioRuntime,
  ParsedEvent,
  SavedVoice,
  Track,
  VoiceApi,
  VoiceModelInfo,
} from "@wasifyai/client";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { AudioToolWorkspace } from "./AudioToolWorkspace";
import { TrackList, trackKind } from "./TrackList";
import { modelOption, stateText } from "./format";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

const tool = (over: Partial<VoiceModelInfo> = {}): VoiceModelInfo => ({
  id: "htdemucs",
  title: "HTDemucs (4 stems)",
  licence: "MIT",
  engine: "audiocpp",
  family: "htdemucs",
  tasks: ["separate"],
  recommended: ["separate"],
  languages: [],
  sample_rate: 44100,
  commercial_use: "yes",
  licence_evidence: "https://github.com/facebookresearch/demucs",
  reviewed: "2026-10-16",
  measured: { platform: "darwin-arm64", speed_x: 2.2, memory_gb: null, load_s: 9 },
  voices: [],
  default_voice: null,
  options: [],
  music: {},
  separate: { stems: ["drums", "bass", "other", "vocals"], max_source_s: 600 },
  state: "ready",
  files_ready: true,
  runtime_ready: true,
  bytes_missing: 0,
  ...over,
});

const runtime = (): AudioRuntime => ({
  installed: true,
  tag: "v0.9.0",
  backend: "metal",
  source: "managed",
  running: false,
  plan: {
    supported: true,
    platform: "darwin-arm64",
    tag: "v0.9.0",
    bytes: 1,
    url: "https://x",
    backend: "metal",
    measured: true,
    found: null,
  },
  install: { state: "idle", step: null, message: "", done_bytes: 0, total_bytes: 0 },
});

const track = (over: Partial<Track> = {}): Track => ({
  id: "t1",
  title: "Summer",
  mode: "song",
  favourite: false,
  parent_id: null,
  edit: {},
  description: "pop",
  lyrics: "",
  instrumental: false,
  model_id: "ace-step-1.5-turbo",
  options: {},
  seed: 1,
  seconds: 20,
  sample_rate: 48000,
  load_s: 0,
  elapsed_s: 1,
  created_at: "2026-10-16T10:00:00Z",
  updated_at: "2026-10-16T10:00:00Z",
  audio_url: "http://127.0.0.1/a.wav",
  ...over,
});

const clone = (over: Partial<SavedVoice> = {}): SavedVoice => ({
  id: "v1",
  name: "Ann",
  kind: "clone",
  description: "",
  reference_text: "",
  reference_seconds: 5,
  consent: { basis: "own" },
  created_at: "",
  updated_at: "",
  ...over,
});

function api(models: VoiceModelInfo[], over: Record<string, unknown> = {}): VoiceApi {
  return {
    runtime: vi.fn(async () => runtime()),
    models: vi.fn(async () => models),
    tracks: vi.fn(async () => [track()]),
    speeches: vi.fn(async () => []),
    voices: vi.fn(async () => []),
    formats: vi.fn(async () => ["wav"]),
    importTrack: vi.fn(),
    words: vi.fn(),
    ...over,
  } as unknown as VoiceApi;
}

const runsThat = (events: ParsedEvent[]) => ({
  startRun: vi.fn(async (_p: string, _i: object, _s: AbortSignal, on: (e: ParsedEvent) => void) => {
    for (const e of events) on(e);
  }),
});

const finished = (tracks: Record<string, unknown>[]) =>
  ev("done", { outputs: { status: "done", tracks } });

// Radix's pointer handling needs these in jsdom
beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
});

async function pickSource(name: RegExp = /^Summer/) {
  await userEvent.click(await screen.findByRole("combobox", { name: /which/i }));
  await userEvent.click(await screen.findByRole("option", { name }));
}

describe("splitting a recording", () => {
  it("keeps the parts that were left ticked and shows each one", async () => {
    const runs = runsThat([
      ev("node", { label: "Splitting" }),
      finished([
        {
          track_id: "p1",
          title: "Summer (vocals)",
          seconds: 20,
          audio_url: "http://x/v.wav",
          stem: "vocals",
        },
      ]),
    ]);
    render(<AudioToolWorkspace api={api([tool()])} runs={runs} tool="separate" />);
    await pickSource();
    for (const name of ["drums", "bass", "other"]) {
      await userEvent.click(screen.getByRole("checkbox", { name }));
    }
    await userEvent.click(screen.getByRole("button", { name: "Split the song" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "separate",
      source_track: "t1",
      model: "htdemucs",
      stems: ["vocals"],
    });
    const result = await screen.findByRole("region", { name: "Result" });
    expect(result.textContent).toContain("vocals");
  });

  it("sends no list when every part is kept, and cannot run with none", async () => {
    const runs = runsThat([finished([{ track_id: "p", title: "x", seconds: 1, audio_url: "u" }])]);
    render(<AudioToolWorkspace api={api([tool()])} runs={runs} tool="separate" />);
    await pickSource();
    const split = screen.getByRole("button", { name: "Split the song" }) as HTMLButtonElement;
    for (const name of ["drums", "bass", "other", "vocals"]) {
      await userEvent.click(screen.getByRole("checkbox", { name }));
    }
    expect(split.disabled).toBe(true);
    for (const name of ["drums", "bass", "other", "vocals"]) {
      await userEvent.click(screen.getByRole("checkbox", { name }));
    }
    await userEvent.click(split);
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "separate",
      source_track: "t1",
      model: "htdemucs",
    });
  });

  it("says why when the engine refuses, and a recording that is too long cannot be sent", async () => {
    const runs = runsThat([
      ev("done", {
        outputs: {
          status: "refused",
          refusal: { code: "too_long", message: "Cut it shorter first." },
        },
      }),
    ]);
    const long = tool({ separate: { stems: ["vocals"], max_source_s: 10 } });
    render(<AudioToolWorkspace api={api([long])} runs={runs} tool="separate" />);
    await pickSource();
    expect(await screen.findByText(/takes a recording of up to 0:10/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Split the song" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("shows the refusal of the engine in words", async () => {
    const runs = runsThat([
      ev("done", {
        outputs: { status: "refused", refusal: { code: "no_parts", message: "Nothing came out." } },
      }),
    ]);
    render(<AudioToolWorkspace api={api([tool()])} runs={runs} tool="separate" />);
    await pickSource();
    await userEvent.click(screen.getByRole("button", { name: "Split the song" }));
    expect(await screen.findByText("Nothing came out.")).toBeTruthy();
  });

  it("adds a recording from this computer and chooses it", async () => {
    const added = track({ id: "t9", title: "Dad", mode: "imported" });
    const importTrack = vi.fn(async () => added);
    render(
      <AudioToolWorkspace
        api={api([tool()], { importTrack })}
        runs={runsThat([])}
        tool="separate"
      />,
    );
    const file = new File(["RIFF"], "dad.wav", { type: "audio/wav" });
    await userEvent.upload(
      await screen.findByLabelText("Add a recording from this computer"),
      file,
    );
    await waitFor(() => expect(importTrack).toHaveBeenCalledWith(file));
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: /which/i })).toHaveTextContent("Dad"),
    );
  });
});

describe("changing a voice", () => {
  const convert = tool({
    id: "meanvc2",
    title: "MeanVC2",
    tasks: ["convert"],
    recommended: ["convert"],
    separate: undefined,
    convert: { reference_seconds: [3, 30], max_source_s: 300 },
  });

  it("asks for a saved voice first when there is none", async () => {
    const onOpenVoices = vi.fn();
    render(
      <AudioToolWorkspace
        api={api([convert])}
        runs={runsThat([])}
        tool="convert"
        onOpenVoices={onOpenVoices}
      />,
    );
    expect(await screen.findByText(/Save a voice from a recording first/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Open Voices" }));
    expect(onOpenVoices).toHaveBeenCalled();
    await pickSource();
    expect(
      (screen.getByRole("button", { name: "Change the voice" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("sends the saved voice and the model that were chosen, and says whose voice it is", async () => {
    const runs = runsThat([
      finished([
        { track_id: "c1", title: "Summer (as Ann)", seconds: 20, audio_url: "http://x/c.wav" },
      ]),
    ]);
    render(
      <AudioToolWorkspace
        api={api([convert], {
          voices: vi.fn(async () => [
            clone(),
            clone({ id: "v2", name: "Bo", consent: { basis: "permission" } }),
          ]),
        })}
        runs={runs}
        tool="convert"
      />,
    );
    await pickSource();
    await userEvent.click(await screen.findByRole("combobox", { name: "Sound like" }));
    expect(screen.getByRole("option", { name: /^Ann/ }).textContent).toContain("your own voice");
    expect(screen.getByRole("option", { name: /^Bo/ }).textContent).toContain(
      "used with permission",
    );
    await userEvent.click(screen.getByRole("option", { name: /^Bo/ }));
    await userEvent.click(screen.getByRole("button", { name: "Change the voice" }));
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "convert",
      source_track: "t1",
      saved_voice: "v2",
      model: "meanvc2",
    });
  });
});

describe("changing the words", () => {
  const edit = tool({
    id: "dots-tts-edit",
    title: "dots.tts Edit",
    tasks: ["edit"],
    recommended: [],
    commercial_use: "conditional",
    separate: undefined,
    speech_edit: { max_changes: 5, max_source_s: 30 },
  });

  it("writes down what the recording says, and sends the old and the new words", async () => {
    const runs = runsThat([
      finished([
        { track_id: "e1", title: "Summer (edited)", seconds: 5, audio_url: "http://x/e.wav" },
      ]),
    ]);
    const words = vi.fn(async () => ({
      text: "Hello brave world.",
      seconds: 5,
      model: "parakeet",
    }));
    render(<AudioToolWorkspace api={api([edit], { words })} runs={runs} tool="edit" />);
    await pickSource();
    const run = screen.getByRole("button", { name: "Change the words" }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Write down what it says" }));
    const after = await screen.findByLabelText("What it should say");
    await waitFor(() => expect((after as HTMLTextAreaElement).value).toBe("Hello brave world."));
    expect(words).toHaveBeenCalledWith({ kind: "track", id: "t1" });
    expect(run.disabled).toBe(true); // nothing changed yet
    await userEvent.clear(after);
    await userEvent.type(after, "Hello small world.");
    expect(run.disabled).toBe(false);
    await userEvent.click(run);
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "speech_edit",
      source_track: "t1",
      old_text: "Hello brave world.",
      text: "Hello small world.",
      model: "dots-tts-edit",
    });
  });

  it("says in words when the words could not be written down", async () => {
    const words = vi.fn(async () => {
      throw new Error("Set up speech to text first.");
    });
    render(<AudioToolWorkspace api={api([edit], { words })} runs={runsThat([])} tool="edit" />);
    await pickSource();
    await userEvent.click(screen.getByRole("button", { name: "Write down what it says" }));
    expect(await screen.findByText("Set up speech to text first.")).toBeTruthy();
  });
});

describe("the library and the model list", () => {
  it("offers the tools on a track, and make-it-again only for what was made from words", async () => {
    const onTool = vi.fn();
    const items = [
      track({ id: "a", title: "A song" }),
      track({
        id: "b",
        title: "A part",
        mode: "stem",
        edit: { stem: "vocals" },
        model_id: "htdemucs",
      }),
      track({ id: "c", title: "Dad", mode: "imported", model_id: "" }),
    ];
    render(
      <TrackList
        api={api([], { tracks: vi.fn(async () => items) })}
        onAgain={() => undefined}
        onEdit={() => undefined}
        onTool={onTool}
      />,
    );
    expect(await screen.findAllByRole("button", { name: "Split into parts" })).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "Make it again" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Change it" })).toHaveLength(1);
    await userEvent.click(
      screen.getAllByRole("button", { name: "Change the words" })[1] as HTMLElement,
    );
    expect(onTool).toHaveBeenCalledWith(items[1], "words");
  });

  it("names what each kind of track is", () => {
    expect(trackKind(track({ mode: "stem", edit: { stem: "vocals" } }))).toBe("part: vocals");
    expect(trackKind(track({ mode: "converted", edit: { voice: "Ann" } }))).toBe(
      "in the voice of Ann",
    );
    expect(trackKind(track({ mode: "edited" }))).toBe("words changed");
    expect(trackKind(track({ mode: "imported" }))).toBe("added from a file");
  });

  it("says a model on the image engine needs the image engine, not speech", () => {
    const comfy = tool({ engine: "comfyui", state: "needs_runtime", tasks: ["music"] });
    expect(stateText(comfy)).toBe("Needs the image engine");
    expect(modelOption(comfy, "music")).toContain("needs the image engine");
    expect(stateText(tool({ state: "needs_runtime" }))).toBe("Needs the speech runtime");
  });
});
