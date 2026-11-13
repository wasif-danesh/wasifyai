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
import { LipSyncWorkspace } from "./LipSyncWorkspace";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

const model = (over: Partial<VoiceModelInfo> = {}): VoiceModelInfo => ({
  id: "musetalk-v15",
  title: "MuseTalk 1.5",
  engine: "sidecar",
  family: "musetalk",
  tasks: ["lipsync"],
  recommended: ["lipsync"],
  languages: ["multi"],
  sample_rate: 0,
  measured: { platform: "darwin-arm64", speed_x: 0.2, memory_gb: 11.8, load_s: null },
  voices: [],
  default_voice: null,
  options: [],
  music: {},
  lipsync: {
    max_voice_s: 300,
    sizes: [480, 720],
    default_size: 720,
    speed_pixels: 576000,
    fps: 25,
    mark: "required",
  },
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
  await screen.findByAltText(/^The face to bring to life/);
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
  it("needs only the picture and the words before it can be made, and asks nothing about them", async () => {
    render(<LipSyncWorkspace api={api()} runs={runsThat([])} />);
    await screen.findByRole("heading", { name: "The picture" });
    expect(screen.queryByText(/AI-generated/)).toBeNull();
    expect(makeButton().disabled).toBe(true);
    await addFace();
    expect(makeButton().disabled).toBe(true); // no words yet
    await userEvent.type(screen.getByLabelText("What should it say?"), "Good evening, everyone.");
    expect(makeButton().disabled).toBe(false);
    expect(screen.queryByRole("radio", { name: /picture of me|own voice/ })).toBeNull();
  });

  it("sends words with the picture, then lists the new video", async () => {
    const runs = runsThat([ev("node", { label: "Speaking" }), finished]);
    const clips = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([clip()]);
    render(<LipSyncWorkspace api={api({ clips })} runs={runs} />);
    await addFace();
    await userEvent.type(screen.getByLabelText("What should it say?"), "Good evening, everyone.");
    await userEvent.click(makeButton());
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "lipsync",
      picture: "p1",
      text: "Good evening, everyone.",
      model: "musetalk-v15",
      size: 720,
    });
    // the new video plays on the stage
    const stage = screen.getByRole("region", { name: "Result" });
    await waitFor(() => expect(stage.textContent).toContain("Mona says hello"));
    expect(stage.querySelector("video")).toHaveAttribute("src", "http://x/c.mp4");
  });

  it("makes the shape and size chosen, shows the crop, and says the size and the time", async () => {
    const runs = runsThat([finished]);
    render(<LipSyncWorkspace api={api()} runs={runs} />);
    await addFace(); // 300x447
    expect(screen.getByText("The video will be 720×1072 pixels.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Portrait 9:16/ }));
    await userEvent.click(screen.getByRole("button", { name: /480p/ }));
    expect(screen.getByRole("button", { name: /480p/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("The video will be 480×848 pixels.")).toBeTruthy();
    const crop = screen.getByAltText(/as the video will show it/);
    expect(crop.style.aspectRatio).toBe("480 / 848");
    await userEvent.type(screen.getByLabelText("What should it say?"), "Good evening, everyone.");
    expect(screen.getByText(/of work on this computer/)).toBeTruthy();
    await userEvent.click(makeButton());
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toMatchObject({ shape: "9:16", size: 480 });
  });

  it("makes a video from any recording, without asking whose voice it is", async () => {
    const runs = runsThat([finished]);
    render(<LipSyncWorkspace api={api()} runs={runs} />);
    await addFace();
    await userEvent.click(screen.getByRole("radio", { name: "A recording" }));
    await chooseRecording(/^My recording/);
    expect(makeButton().disabled).toBe(false);
    await chooseRecording(/^Hello there/);
    await userEvent.click(makeButton());
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "lipsync",
      picture: "p1",
      source_speech: "s1",
      model: "musetalk-v15",
      size: 720,
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

  it("asks for nothing to be set up while the model runs on the person's key", async () => {
    const a = api({ lipsyncEngine: vi.fn(async () => engine({ installed: false })) }, [
      model({
        id: "key:lipsync",
        title: "Kling Avatar v2 · with your key",
        engine: "remote",
        family: "fal",
        measured: { platform: "", speed_x: null, memory_gb: null, load_s: null },
      }),
    ]);
    render(<LipSyncWorkspace api={a} runs={runsThat([])} />);
    await addFace();
    expect(screen.queryByRole("button", { name: /Set up lip sync \(/ })).toBeNull();
    expect(screen.queryByText(/Needs the lip sync engine/)).toBeNull();
  });

  it("says what a cloud model costs and how long it takes for this voice, and leaves it to the person", async () => {
    const runs = runsThat([finished]);
    const a = api({}, [
      model({
        id: "key:lipsync",
        title: "Fabric 1.0 Fast · with your key",
        engine: "remote",
        family: "fal",
        measured: { platform: "", speed_x: null, memory_gb: null, load_s: null },
        lipsync: {
          max_voice_s: 60,
          sizes: [480, 720],
          default_size: 480,
          fps: 25,
          where: "fal.ai",
          price_per_s: { "480": 0.1, "720": 0.2 },
          work_per_s: { "480": 25 },
          frame: "square",
          frame_short: { "480": 640 },
        },
      }),
    ]);
    render(
      <LipSyncWorkspace
        api={a}
        runs={runs}
        lead="Make the face in a picture say your words or a recording. It runs on this computer."
      />,
    );
    expect(await screen.findByText(/It runs on fal\.ai with your key\.$/)).toBeTruthy();
    await addFace();
    // Fabric makes a square whatever the picture: no shape to choose, and the size it made
    expect(screen.queryByRole("button", { name: /Portrait/ })).toBeNull();
    expect(screen.getByText(/Fabric 1\.0 Fast always makes a square video/)).toBeTruthy();
    expect(screen.getByText("The video will be about 640×640 pixels.")).toBeTruthy();
    // three words are about two seconds of speech: 50 s of work and 20 cents at 480p
    await userEvent.type(screen.getByLabelText("What should it say?"), "Good evening, everyone.");
    expect(
      screen.getByText(/^About 50 seconds on fal\.ai and about \$0\.20 for .* of video at 480p\.$/),
    ).toBeTruthy();
    expect(screen.queryByText(/of work on this computer/)).toBeNull();
    // 720p was not timed: the price is said, and that the time is not known
    await userEvent.click(screen.getByRole("button", { name: /720p/ }));
    expect(
      screen.getByText(/^About \$0\.40 on fal\.ai for .* at 720p\. Its time is not measured\.$/),
    );
    // its size at 720p was not measured: only that it is square
    expect(screen.getByText("The video will be square.")).toBeTruthy();
    // nothing stops a long or a short voice: the person decides and makes it
    expect(makeButton().disabled).toBe(false);
    await userEvent.click(makeButton());
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toMatchObject({ shape: "1:1", size: 720 });
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
  it("clears the picture, so the next video starts from a new one", async () => {
    const runs = runsThat([finished]);
    const clips = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([clip()]);
    render(<LipSyncWorkspace api={api({ clips })} runs={runs} />);
    await addFace();
    await userEvent.type(screen.getByLabelText("What should it say?"), "Good evening.");
    await userEvent.click(makeButton());
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Result" }).textContent).toContain(
        "Mona says hello",
      ),
    );
    expect(makeButton().disabled).toBe(true); // a new picture is needed
  });
});
