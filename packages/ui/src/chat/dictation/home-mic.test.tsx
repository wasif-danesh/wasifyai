// @vitest-environment jsdom
// The Mic as the home screen offers it (ADR-0083, decision 5): shown where the engine can write words down, with a setup
// card where a speech model can be got, and absent where it cannot.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  type AssistantApi,
  type AudioRuntime,
  HOSTED_RUNTIME,
  type ImagesApi,
  type VoiceApi,
  type VoiceModelInfo,
} from "@wasifyai/client";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { AssistantHome } from "../AssistantHome";

const runs = { startRun: vi.fn(async () => {}), watchRun: vi.fn(async () => {}) };
const images = {} as ImagesApi;
const assistant = {
  options: vi.fn(async () => ({ thinking: false })),
  list: vi.fn(async () => []),
} as unknown as AssistantApi;

const model = (over: Partial<VoiceModelInfo> = {}) =>
  ({
    id: "parakeet-tdt-0.6b-v3",
    title: "Parakeet TDT 0.6B v3",
    tasks: ["transcribe"],
    recommended: ["transcribe"],
    state: "ready",
    bytes_missing: 0,
    source: "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3",
    ...over,
  }) as VoiceModelInfo;
const runtime = (installed: boolean): AudioRuntime => ({
  ...HOSTED_RUNTIME,
  installed,
  plan: { ...HOSTED_RUNTIME.plan, supported: true, bytes: 40_000_000 },
});

function voiceThat(models: () => VoiceModelInfo[], rt: () => AudioRuntime): VoiceApi {
  return {
    models: vi.fn(async () => models()),
    runtime: vi.fn(async () => rt()),
    installRuntime: vi.fn(async () => rt()),
    dictate: vi.fn(async () => ({ text: "hello", seconds: 1, model: "m", displaced: null })),
  } as unknown as VoiceApi;
}

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

// The chat is a separate chunk (AssistantHome loads it lazily). Loading assistant-ui took longer than the default wait on a slow
// Windows runner, so the first test found an empty page. Load it once here, with room to do so.
beforeAll(async () => {
  await import("../ChatScreen");
}, 60_000);

afterEach(() => vi.restoreAllMocks());

describe("the home screen", () => {
  it("shows the Mic when a speech model is ready", async () => {
    home({
      voice: voiceThat(
        () => [model()],
        () => runtime(true),
      ),
    });
    expect(await screen.findByRole("button", { name: /^Mic/ })).toBeInTheDocument();
  });

  it("has no Mic without a speech client, or where there is no speech-to-text model", async () => {
    home();
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: /^Mic/ })).toBeNull();
  });

  it("has no Mic on the web when the service offers no transcription", async () => {
    home({
      voice: voiceThat(
        () => [],
        () => HOSTED_RUNTIME,
      ),
    });
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(assistant.options).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /^Mic/ })).toBeNull();
  });

  it("has no Mic where a model is missing and nothing here can fetch it (the web)", async () => {
    const voice = voiceThat(
      () => [model({ state: "can_install", bytes_missing: 9e8 })],
      () => runtime(false),
    );
    home({ voice });
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(voice.models).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /^Mic/ })).toBeNull();
  });

  it("offers the missing model with its size, asks nothing until the button is pressed, then sets up", async () => {
    let installed = false;
    let have = false;
    const voice = voiceThat(
      () => [model(have ? {} : { state: "can_install", bytes_missing: 915_733_744 })],
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
    await user.click(await screen.findByRole("button", { name: /^Mic/ }));
    const card = await screen.findByRole("region", { name: "Set up dictation" });
    expect(card).toHaveTextContent("Parakeet TDT 0.6B v3");
    expect(card).not.toHaveTextContent("CC-BY");
    expect(card).toHaveTextContent("huggingface.co");
    expect(card).toHaveTextContent("956 MB"); // the model and the 40 MB runtime
    expect(voice.installRuntime).not.toHaveBeenCalled(); // nothing is fetched before the click
    expect(getSpeechModel).not.toHaveBeenCalled();

    await user.click(within(card).getByRole("button", { name: /^Download/ }));
    expect(await screen.findByText("Dictation is ready. Press Mic to start.")).toBeInTheDocument();
    expect(voice.installRuntime).toHaveBeenCalledWith(40_000_000);
    expect(getSpeechModel).toHaveBeenCalledWith("parakeet-tdt-0.6b-v3", expect.any(Function));
  });
});
