// @vitest-environment jsdom
// Read aloud as the home screen offers it (ADR-0083, CU3): shown where the engine has a voice, with a setup card where one can be got,
// and absent where it cannot. Sound goes through the page's audio element, which is faked here.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  type AssistantApi,
  type AudioRuntime,
  HOSTED_RUNTIME,
  type ImagesApi,
  type OnEvent,
  type ParsedEvent,
  type VoiceApi,
  type VoiceModelInfo,
} from "@wasifyai/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantHome } from "../AssistantHome";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

const runs = {
  startRun: vi.fn(async (_p: string, _i: object, _s: AbortSignal, on: OnEvent) => {
    on(ev("token", { text: "A short answer." }));
    on(ev("done", { outputs: { status: "done", conversation_id: "c1", title: "Hi" } }));
  }),
  watchRun: vi.fn(async () => {}),
};
const images = {} as ImagesApi;
const assistant = {
  options: vi.fn(async () => ({ thinking: false })),
  list: vi.fn(async () => []),
  setHead: async () => {},
} as unknown as AssistantApi;

const kokoro = (over: Partial<VoiceModelInfo> = {}) =>
  ({
    id: "kokoro-82m",
    title: "Kokoro 82M",
    tasks: ["speak"],
    recommended: ["speak"],
    languages: ["en-US", "en-GB"],
    state: "ready",
    bytes_missing: 0,
    source: "https://huggingface.co/hexgrad/Kokoro-82M",
    ...over,
  }) as VoiceModelInfo;
const runtime = (installed: boolean): AudioRuntime => ({
  ...HOSTED_RUNTIME,
  installed,
  plan: { ...HOSTED_RUNTIME.plan, supported: true, bytes: 40_000_000 },
});

function voiceThat(models: () => VoiceModelInfo[], rt: () => AudioRuntime) {
  return {
    // the same list for any task: the readiness code picks by the task a model lists
    models: vi.fn(async () => models()),
    runtime: vi.fn(async () => rt()),
    installRuntime: vi.fn(async () => rt()),
    readAloud: vi.fn(async (_t: string, part = 0) => ({
      wav: new Blob(["RIFF"], { type: "audio/wav" }),
      part,
      parts: 1,
      truncated: false,
      seconds: 1,
      model: "kokoro-82m",
      displaced: null,
    })),
  } as unknown as VoiceApi;
}

class FakeAudio {
  static played = 0;
  src = "";
  volume = 1;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play = vi.fn(async () => {
    FakeAudio.played++;
  });
  pause = vi.fn();
  removeAttribute() {}
}

// The chat is a separate chunk (AssistantHome loads it lazily). Loading assistant-ui took longer than the default wait on a slow
// Windows runner, so the first test found an empty page. Load it once here, with room to do so.
beforeAll(async () => {
  await import("../ChatScreen");
}, 60_000);

beforeEach(() => {
  FakeAudio.played = 0;
  vi.stubGlobal("Audio", FakeAudio);
  URL.createObjectURL = () => "blob:x";
  URL.revokeObjectURL = () => {};
});
afterEach(() => vi.unstubAllGlobals());

function home(props: Partial<React.ComponentProps<typeof AssistantHome>> = {}) {
  return render(
    <AssistantHome
      runs={runs}
      assistant={assistant}
      images={images}
      conversationId={null}
      onAdopt={() => {}}
      onNewChat={() => {}}
      {...props}
    />,
  );
}
async function reply(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByRole("textbox", { name: "Message" }), "Hi{Enter}");
  await screen.findByText("A short answer.");
}

describe("the home screen", () => {
  it("offers Read aloud on a reply when a voice is ready, and reads it with the voice", async () => {
    const voice = voiceThat(
      () => [kokoro()],
      () => runtime(true),
    );
    const user = userEvent.setup();
    home({ voice });
    await reply(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    await waitFor(() => expect(FakeAudio.played).toBeGreaterThan(0));
    expect(voice.readAloud).toHaveBeenCalledWith("A short answer.", 0, expect.any(AbortSignal));
  });

  it("has no Read aloud without a speech client or without a text-to-speech model", async () => {
    const user = userEvent.setup();
    const { unmount } = home();
    await reply(user);
    expect(screen.queryByRole("button", { name: /read this reply/i })).toBeNull();
    unmount();
    const voice = voiceThat(
      () => [],
      () => HOSTED_RUNTIME,
    );
    home({ voice });
    await reply(user);
    await waitFor(() => expect(voice.models).toHaveBeenCalledWith("speak"));
    expect(screen.queryByRole("button", { name: /read this reply/i })).toBeNull();
  });

  it("has no Read aloud where the voice is missing and nothing here can fetch it (the web)", async () => {
    const voice = voiceThat(
      () => [kokoro({ state: "can_install", bytes_missing: 189_549_408 })],
      () => runtime(false),
    );
    const user = userEvent.setup();
    home({ voice });
    await reply(user);
    await waitFor(() => expect(voice.models).toHaveBeenCalledWith("speak"));
    expect(screen.queryByRole("button", { name: /read this reply/i })).toBeNull();
  });

  it("offers the missing voice with its size, fetches nothing before the click, then sets up and reads", async () => {
    let installed = false;
    let have = false;
    const voice = voiceThat(
      () => [kokoro(have ? {} : { state: "can_install", bytes_missing: 189_549_408 })],
      () => runtime(installed),
    );
    vi.mocked(voice.installRuntime).mockImplementation(async () => {
      installed = true;
      return runtime(true);
    });
    const getSpeechModel = vi.fn(async (_id: string, onProgress: (f: number) => void) => {
      onProgress(0.5);
      have = true;
    });
    const user = userEvent.setup();
    home({ voice, getSpeechModel });
    await reply(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    const card = await screen.findByRole("region", { name: "Set up read aloud" });
    expect(card).toHaveTextContent("Kokoro 82M");
    expect(card).not.toHaveTextContent("Apache");
    expect(card).toHaveTextContent("huggingface.co");
    expect(card).toHaveTextContent("230 MB"); // the voice and the 40 MB runtime
    expect(card).toHaveTextContent("English");
    expect(voice.installRuntime).not.toHaveBeenCalled();
    expect(getSpeechModel).not.toHaveBeenCalled();
    expect(voice.readAloud).not.toHaveBeenCalled();

    await user.click(within(card).getByRole("button", { name: /^Download/ }));
    expect(
      await screen.findByText("Read aloud is ready. Press Read aloud on a reply to hear it."),
    ).toBeInTheDocument();
    expect(voice.installRuntime).toHaveBeenCalledWith(40_000_000);
    expect(getSpeechModel).toHaveBeenCalledWith("kokoro-82m", expect.any(Function));
    expect(FakeAudio.played).toBe(0); // getting the voice does not read anything

    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    await waitFor(() => expect(voice.readAloud).toHaveBeenCalledTimes(1));
  });
});
