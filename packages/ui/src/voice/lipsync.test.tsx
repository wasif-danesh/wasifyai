// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  Clip,
  LipSyncEngine,
  ParsedEvent,
  Speech,
  Track,
  VoiceApi,
  VoiceModelInfo,
} from "@wasifyai/client";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { LipSyncWorkspace, MARK, PICTURE_TEXT, VOICE_TEXT } from "./LipSyncWorkspace";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

const model = (over: Partial<VoiceModelInfo> = {}): VoiceModelInfo => ({
  id: "musetalk-v15",
  title: "MuseTalk 1.5",
  licence: "MIT",
  engine: "sidecar",
  family: "musetalk",
  tasks: ["lipsync"],
  recommended: ["lipsync"],
  languages: ["multi"],
  sample_rate: 0,
  commercial_use: "yes",
  licence_evidence: "https://huggingface.co/TMElyralab/MuseTalk",
  reviewed: "2026-10-16",
  measured: { platform: "darwin-arm64", speed_x: 0.2, memory_gb: 11.8, load_s: null },
  voices: [],
  default_voice: null,
  options: [],
  music: {},
  lipsync: { max_voice_s: 300, max_side: 768, fps: 25, mark: "required" },
  state: "ready",
  files_ready: true,
  runtime_ready: true,
  bytes_missing: 0,
  ...over,
});

const engine = (over: Partial<LipSyncEngine> = {}): LipSyncEngine => ({
  installed: true,
  source: "managed",
  running: false,
  plan: {
    supported: true,
    platform: "darwin-arm64",
    commit: "0a89dec",
    bytes: 1_516_000_000,
    uv: true,
  },
  install: { state: "idle", step: null, message: "", done_bytes: 0, total_bytes: 0 },
  ...over,
});

const track = (over: Partial<Track> = {}): Track =>
  ({
    id: "t1",
    title: "My recording",
    mode: "imported",
    favourite: false,
    parent_id: null,
    edit: {},
    description: "",
    lyrics: "",
    instrumental: false,
    model_id: "",
    options: {},
    seed: null,
    seconds: 12,
    sample_rate: 44100,
    load_s: 0,
    elapsed_s: 0,
    created_at: "",
    updated_at: "",
    audio_url: "http://x/a.wav",
    ...over,
  }) as Track;

const speech = (): Speech =>
  ({ id: "s1", text: "Hello there", seconds: 3, audio_url: "http://x/s.wav" }) as Speech;

const clip = (over: Partial<Clip> = {}): Clip => ({
  id: "c1",
  title: "Mona says hello",
  model_id: "musetalk-v15",
  script: "Hello",
  voice: { kind: "speech", id: "s1" },
  seconds: 5.4,
  fps: 25,
  width: 300,
  height: 446,
  consent: { picture: "drawn", voice: "generated", mark: MARK },
  favourite: false,
  load_s: 0,
  elapsed_s: 30,
  created_at: "",
  updated_at: "",
  video_url: "http://x/c.mp4",
  picture_url: "http://x/p.png",
  ...over,
});

function api(over: Record<string, unknown> = {}, models = [model()]): VoiceApi {
  return {
    runtime: vi.fn(async () => ({
      installed: true,
      install: { state: "idle", step: null, message: "", done_bytes: 0, total_bytes: 0 },
    })),
    models: vi.fn(async () => models),
    lipsyncEngine: vi.fn(async () => engine()),
    installLipsyncEngine: vi.fn(async () =>
      engine({
        install: {
          state: "installing",
          step: "source",
          message: "Getting MuseTalk",
          done_bytes: 1,
          total_bytes: 2,
        },
      }),
    ),
    clips: vi.fn(async () => []),
    tracks: vi.fn(async () => [track()]),
    speeches: vi.fn(async () => [speech()]),
    addPicture: vi.fn(async () => ({ id: "p1", width: 300, height: 447, url: "http://x/p.png" })),
    importTrack: vi.fn(async () => track({ id: "t9", title: "Dad" })),
    updateClip: vi.fn(),
    removeClip: vi.fn(async () => undefined),
    downloadClip: vi.fn(async () => new Blob(["x"])),
    ...over,
  } as unknown as VoiceApi;
}

const runsThat = (events: ParsedEvent[]) => ({
  startRun: vi.fn(async (_p: string, _i: object, _s: AbortSignal, on: (e: ParsedEvent) => void) => {
    for (const e of events) on(e);
  }),
});

const finished = ev("done", {
  outputs: {
    status: "done",
    clip_id: "c1",
    title: "Hello",
    seconds: 5,
    video_url: "http://x/c.mp4",
  },
});

async function addFace() {
  const input = await screen.findByLabelText("Choose a picture");
  await userEvent.upload(input, new File(["x"], "face.png", { type: "image/png" }));
  await screen.findByAltText("The face to bring to life");
}

const makeButton = () =>
  screen.getByRole("button", { name: /Make the video/ }) as HTMLButtonElement;

// Radix's pointer handling needs these in jsdom
beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
});

async function chooseRecording(name: RegExp) {
  await userEvent.click(screen.getByRole("combobox", { name: "Which recording?" }));
  await userEvent.click(await screen.findByRole("option", { name }));
}

describe("making a talking video", () => {
  it("needs the picture, what it is, and the words before it can be made, and says the mark is always there", async () => {
    render(<LipSyncWorkspace api={api()} runs={runsThat([])} />);
    expect(await screen.findByText(/cannot be turned off/)).toBeTruthy();
    expect(makeButton().disabled).toBe(true);
    await addFace();
    await userEvent.type(screen.getByLabelText("What should it say?"), "Good evening, everyone.");
    expect(makeButton().disabled).toBe(true); // the picture's kind is still not said
    await userEvent.click(screen.getByRole("radio", { name: PICTURE_TEXT.drawn }));
    expect(makeButton().disabled).toBe(false);
  });

  it("sends words with the picture and what was said about it, then lists the new video", async () => {
    const runs = runsThat([ev("node", { label: "Speaking" }), finished]);
    const clips = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([clip()]);
    render(<LipSyncWorkspace api={api({ clips })} runs={runs} />);
    await addFace();
    await userEvent.type(screen.getByLabelText("What should it say?"), "Good evening, everyone.");
    await userEvent.click(screen.getByRole("radio", { name: PICTURE_TEXT.own }));
    await userEvent.click(makeButton());
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "lipsync",
      picture: "p1",
      picture_basis: "own",
      voice_basis: "generated",
      text: "Good evening, everyone.",
      model: "musetalk-v15",
    });
    // the new video plays on the stage with what was said about it
    const stage = screen.getByRole("region", { name: "Result" });
    await waitFor(() => expect(stage.textContent).toContain("Mona says hello"));
    expect(stage.querySelector("video")).toHaveAttribute("src", "http://x/c.mp4");
    expect(stage.textContent).toContain(PICTURE_TEXT.drawn);
    expect(stage.textContent).toContain(VOICE_TEXT.generated);
  });

  it("asks whose voice a recording is, and 'made here' is only offered for speech made here", async () => {
    const runs = runsThat([finished]);
    render(<LipSyncWorkspace api={api()} runs={runs} />);
    await addFace();
    await userEvent.click(screen.getByRole("radio", { name: PICTURE_TEXT.drawn }));
    await userEvent.click(screen.getByRole("radio", { name: "A recording" }));
    await chooseRecording(/^My recording/);
    expect(screen.queryByRole("radio", { name: VOICE_TEXT.generated })).toBeNull();
    expect(makeButton().disabled).toBe(true);
    await userEvent.click(screen.getByRole("radio", { name: VOICE_TEXT.permission }));
    expect(makeButton().disabled).toBe(false);
    await chooseRecording(/^Hello there/);
    expect(screen.getByRole("radio", { name: VOICE_TEXT.generated })).toBeTruthy();
    expect(makeButton().disabled).toBe(true); // the answer was reset with the recording
    await userEvent.click(screen.getByRole("radio", { name: VOICE_TEXT.generated }));
    await userEvent.click(makeButton());
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "lipsync",
      picture: "p1",
      picture_basis: "drawn",
      voice_basis: "generated",
      source_speech: "s1",
      model: "musetalk-v15",
    });
  });

  it("adds a recording from this computer and chooses it", async () => {
    const importTrack = vi.fn(async () => track({ id: "t9", title: "Dad" }));
    render(<LipSyncWorkspace api={api({ importTrack })} runs={runsThat([])} />);
    await userEvent.click(await screen.findByRole("radio", { name: "A recording" }));
    const file = new File(["RIFF"], "dad.wav", { type: "audio/wav" });
    await userEvent.upload(screen.getByLabelText("Add a recording from this computer"), file);
    await waitFor(() => expect(importTrack).toHaveBeenCalledWith(file));
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Which recording?" })).toHaveTextContent("Dad"),
    );
  });

  it("says in words why a video was not made", async () => {
    const runs = runsThat([
      ev("error", {
        code: "no_face",
        message: "No clear face was found in the picture. Try a front-facing one.",
      }),
    ]);
    render(<LipSyncWorkspace api={api()} runs={runs} />);
    await addFace();
    await userEvent.type(screen.getByLabelText("What should it say?"), "Hello there.");
    await userEvent.click(screen.getByRole("radio", { name: PICTURE_TEXT.drawn }));
    await userEvent.click(makeButton());
    expect((await screen.findByRole("alert")).textContent).toContain("front-facing");
  });

  it("says when a picture cannot be added", async () => {
    const addPicture = vi.fn(async () => {
      throw new Error("That picture is larger than 10 MB.");
    });
    render(<LipSyncWorkspace api={api({ addPicture })} runs={runsThat([])} />);
    await userEvent.upload(
      await screen.findByLabelText("Choose a picture"),
      new File(["x"], "big.png", { type: "image/png" }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain("10 MB");
  });
});

describe("the lip sync engine and the videos", () => {
  it("shows the size before setting the engine up, and does it only on a click", async () => {
    const a = api({ lipsyncEngine: vi.fn(async () => engine({ installed: false })) }, [
      model({ state: "needs_runtime" }),
    ]);
    render(<LipSyncWorkspace api={a} runs={runsThat([])} />);
    expect((await screen.findAllByText(/1\.5 GB|1\.4 GB/)).length).toBeGreaterThan(0);
    expect(a.installLipsyncEngine).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Set up lip sync \(/ }));
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(a.installLipsyncEngine).toHaveBeenCalledWith(1_516_000_000));
    expect(makeButton().disabled).toBe(true);
    expect(screen.getAllByText(/Needs the lip sync engine/).length).toBeGreaterThan(0);
  });

  it("says when there is no engine for this computer or the installer is missing", async () => {
    const none = api({
      lipsyncEngine: vi.fn(async () =>
        engine({
          installed: false,
          plan: { supported: false, platform: "win", commit: "x", bytes: 0, uv: true },
        }),
      ),
    });
    const { unmount } = render(<LipSyncWorkspace api={none} runs={runsThat([])} />);
    expect(await screen.findByText(/no lip sync engine for this kind of computer/)).toBeTruthy();
    unmount();
    const nouv = api({
      lipsyncEngine: vi.fn(async () =>
        engine({
          installed: false,
          plan: { supported: true, platform: "darwin-arm64", commit: "x", bytes: 5, uv: false },
        }),
      ),
    });
    render(<LipSyncWorkspace api={nouv} runs={runsThat([])} />);
    expect(
      ((await screen.findByRole("button", { name: /Set up lip sync \(/ })) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText(/repair the app/)).toBeTruthy();
  });

  it("opens a video from the strip, renames, saves and deletes it, asking first", async () => {
    const updateClip = vi.fn(async () => clip({ title: "Hello again" }));
    const removeClip = vi.fn(async () => undefined);
    const downloadClip = vi.fn(async () => new Blob(["x"]));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    render(
      <LipSyncWorkspace
        api={api({ clips: vi.fn(async () => [clip()]), updateClip, removeClip, downloadClip })}
        runs={runsThat([])}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Open: Mona says hello" }));
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    const name = await screen.findByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Hello again{Enter}");
    await waitFor(() => expect(updateClip).toHaveBeenCalledWith("c1", { title: "Hello again" }));
    expect((await screen.findAllByText(/Hello again/)).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Save MP4" }));
    await waitFor(() => expect(downloadClip).toHaveBeenCalledWith("c1"));
    await userEvent.click(
      within(screen.getByRole("region", { name: "Result" })).getByRole("button", {
        name: /Delete/,
      }),
    );
    expect(removeClip).not.toHaveBeenCalled(); // asks first
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() => expect(removeClip).toHaveBeenCalledWith("c1"));
    expect(await screen.findByText(/Nothing made yet/)).toBeTruthy();
  });
});

describe("after a video is made", () => {
  it("clears what the picture was, so the next picture is asked about afresh", async () => {
    const runs = runsThat([finished]);
    const clips = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([clip()]);
    render(<LipSyncWorkspace api={api({ clips })} runs={runs} />);
    await addFace();
    await userEvent.type(screen.getByLabelText("What should it say?"), "Good evening.");
    await userEvent.click(screen.getByRole("radio", { name: PICTURE_TEXT.drawn }));
    await userEvent.click(makeButton());
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Result" }).textContent).toContain(
        "Mona says hello",
      ),
    );
    expect(screen.getByRole("radio", { name: PICTURE_TEXT.drawn })).not.toBeChecked();
  });
});
