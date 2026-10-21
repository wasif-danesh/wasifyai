// @vitest-environment jsdom
// Dictation in the chat box (ADR-0083, decision 5), on both chat screens: press Mic, speak, press Stop, and the words land in the box.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, ImagesApi, OnEvent } from "@wasifyai/client";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatScreen } from "../ChatScreen";
import { useComposerOptions } from "../composer-options";
import { MicError, micProblem } from "./recorder";
import { type MicControl, clock, joinDictation } from "./use-dictation";
import { SPEECH_RATE, encodeWav, peakOf, toSpeechRate } from "./wav";

const assistant: AssistantApi = {
  options: async () => ({ thinking: false }),
  searchStatus: async () => {
    throw new Error("unused");
  },
  updateSearch: async () => {
    throw new Error("unused");
  },
  setHead: async () => {},
  attach: async () => {
    throw new Error("unused");
  },
  unattach: async () => {},
  list: async () => [],
  get: async () => {
    throw new Error("unused");
  },
  rename: async () => {
    throw new Error("unused");
  },
  remove: async () => {},
};
const images = { get: async () => ({}) } as unknown as ImagesApi;
const runs = () => ({
  startRun: vi.fn(async (_p: string, _i: object, _s: AbortSignal, _on: OnEvent) => {}),
  watchRun: vi.fn(async () => {}),
});

type Clip = { seconds: number; peak: number };
function fakeMic(over: Partial<MicControl> = {}, clip: Clip = { seconds: 2, peak: 0.4 }) {
  const cancel = vi.fn();
  const stop = vi.fn(async () => ({ wav: new Blob(["wav"], { type: "audio/wav" }), ...clip }));
  const transcribe = vi.fn(async (_w: Blob) => ({ text: "buy two apples", displaced: null }));
  const control: MicControl = {
    record: vi.fn(async () => ({ label: "MacBook Pro Microphone", stop, cancel })),
    transcribe,
    ...over,
  };
  return { control, stop, cancel, transcribe };
}

beforeEach(() => localStorage.clear());

describe("the clip", () => {
  it("is averaged down to 16 kHz, one channel, 16-bit, in a WAV the runtime reads", () => {
    const input = new Float32Array(480).fill(0.5); // 10 ms at 48 kHz
    const out = toSpeechRate([input.slice(0, 200), input.slice(200)], 48000);
    expect(out).toHaveLength(160);
    expect(out.every((s) => Math.abs(s - 0.5) < 1e-6)).toBe(true);
    const odd = toSpeechRate([Float32Array.from([1, 0, 1, 0, 1, 0])], 32000); // pairs average to 0.5
    expect(Array.from(odd)).toEqual([0.5, 0.5, 0.5]);
    expect(toSpeechRate([], 44100)).toHaveLength(0);
  });

  it("has the header the engine checks, and clips what is too loud", async () => {
    const blob = encodeWav(Float32Array.from([0, 1, -1, 3, -3]));
    const v = new DataView(await blob.arrayBuffer());
    const tag = (at: number) => String.fromCharCode(...[0, 1, 2, 3].map((i) => v.getUint8(at + i)));
    expect([tag(0), tag(8), tag(12), tag(36)]).toEqual(["RIFF", "WAVE", "fmt ", "data"]);
    expect([
      v.getUint16(20, true),
      v.getUint16(22, true),
      v.getUint32(24, true),
      v.getUint16(34, true),
    ]).toEqual([1, 1, SPEECH_RATE, 16]);
    expect(v.getUint32(40, true)).toBe(10);
    expect([44, 46, 48, 50, 52].map((at) => v.getInt16(at, true))).toEqual([
      0, 32767, -32768, 32767, -32768,
    ]);
    expect(blob.type).toBe("audio/wav");
    expect(peakOf(Float32Array.from([0.1, -0.7, 0.3]))).toBeCloseTo(0.7);
  });

  it("joins words after what is in the box with one space", () => {
    expect(joinDictation("", "hello")).toBe("hello");
    expect(joinDictation("Write", "a note")).toBe("Write a note");
    expect(joinDictation("Write ", "a note")).toBe("Write a note");
    expect(joinDictation("Write\n", " a note ")).toBe("Write\na note");
    expect(joinDictation("kept", "  ")).toBe("kept");
    expect(clock(7)).toBe("0:07");
    expect(clock(125)).toBe("2:05");
  });

  it("is recorded by a worklet that the desktop and the web serve from their own files, identical", () => {
    const shared = readFileSync(join(__dirname, "../../../public/recorder-worklet.js"), "utf8");
    const web = readFileSync(
      join(__dirname, "../../../../../apps/web/public/recorder-worklet.js"),
      "utf8",
    );
    expect(web).toBe(shared);
    expect(shared).toContain('registerProcessor("wasifyai-recorder"');
    expect(shared).not.toMatch(/\bfetch\b|XMLHttpRequest|WebSocket/); // it only hands samples to the page
  });
});

describe("a failure to open the microphone", () => {
  it.each([
    ["NotAllowedError", "permission", "privacy settings"],
    ["NotFoundError", "no_microphone", "No microphone was found"],
    ["NotReadableError", "busy", "another app"],
    ["Weird", "failed", "could not be started"],
  ])("%s is said in plain words", (name, problem, words) => {
    const e = micProblem(Object.assign(new Error("raw browser text"), { name }));
    expect(e.problem).toBe(problem);
    expect(e.message).toContain(words);
    expect(e.message).not.toContain("raw browser text");
  });

  it("keeps a problem that already has its words", () => {
    const own = new MicError("unsupported", "This window cannot use a microphone.");
    expect(micProblem(own)).toBe(own);
  });
});

describe("useComposerOptions", () => {
  it("has a Mic only where the engine can write words down", () => {
    expect(renderHook(() => useComposerOptions(null, {})).result.current.bar).toEqual([]);
    const { result } = renderHook(() => useComposerOptions(null, { mic: fakeMic().control }));
    expect(result.current.bar.map((o) => o.id)).toEqual(["mic"]);
    expect(result.current.bar[0]).toMatchObject({ label: "Mic", pressed: false, disabled: false });
    expect(result.current.runInput).toEqual({}); // the microphone changes nothing about the message that is sent
  });
});

describe("the chat", () => {
  const Screen = ChatScreen;
  const box = () => screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
  const open = (mic: MicControl | undefined, run = runs()) => {
    render(<Screen runs={run} assistant={assistant} images={images} composerOptions={{ mic }} />);
    return run;
  };

  it("has no Mic where the engine cannot transcribe", () => {
    open(undefined);
    expect(screen.queryByRole("button", { name: /^Mic/ })).toBeNull();
  });

  it("records, shows which microphone listens, then writes the words in the box without sending them", async () => {
    const { control, stop, transcribe } = fakeMic();
    const user = userEvent.setup();
    const run = open(control);
    await user.type(box(), "Please");
    await user.click(screen.getByRole("button", { name: /^Mic/ }));

    const listening = await screen.findByText(/Listening with MacBook Pro Microphone/);
    expect(listening).toHaveTextContent("0:00");
    expect(screen.getByRole("button", { name: /^Stop/ })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: /^Stop/ }));
    await waitFor(() => expect(box()).toHaveValue("Please buy two apples"));
    expect(stop).toHaveBeenCalledOnce();
    expect(transcribe).toHaveBeenCalledOnce();
    expect(screen.queryByText(/Listening/)).toBeNull();
    expect(screen.getByRole("button", { name: /^Mic/ })).toBeEnabled();
    expect(run.startRun).not.toHaveBeenCalled(); // never sent by itself
    await user.type(box(), " today"); // and it is the person's to change
    expect(box()).toHaveValue("Please buy two apples today");
  });

  it("says Transcribing… while the words are being written down", async () => {
    let finish: (v: { text: string }) => void = () => {};
    const { control } = fakeMic({
      transcribe: () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    });
    const user = userEvent.setup();
    open(control);
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    await user.click(await screen.findByRole("button", { name: /^Stop/ }));
    expect(await screen.findByText("Transcribing…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Mic/ })).toBeDisabled();
    act(() => finish({ text: "done" }));
    await waitFor(() => expect(box()).toHaveValue("done"));
    expect(screen.queryByText("Transcribing…")).toBeNull();
  });

  it("throws a cancelled clip away and releases the microphone", async () => {
    const { control, cancel, transcribe } = fakeMic();
    const user = userEvent.setup();
    open(control);
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(cancel).toHaveBeenCalledOnce();
    expect(transcribe).not.toHaveBeenCalled();
    expect(screen.queryByText(/Listening/)).toBeNull();
    expect(box()).toHaveValue("");
  });

  it("lets go of the microphone if the screen goes away while it is listening", async () => {
    const { control, cancel } = fakeMic();
    const user = userEvent.setup();
    const view = render(
      <Screen
        runs={runs()}
        assistant={assistant}
        images={images}
        composerOptions={{ mic: control }}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    await screen.findByText(/Listening/);
    view.unmount();
    expect(cancel).toHaveBeenCalledOnce();
  });

  it.each([
    [
      "the microphone is refused",
      new MicError("permission", "The microphone is turned off for this app."),
      /turned off/,
    ],
    [
      "there is none",
      new MicError("no_microphone", "No microphone was found."),
      /No microphone was found/,
    ],
  ])("says in words when %s, and goes back to idle", async (_what, error, words) => {
    const { control } = fakeMic({ record: async () => Promise.reject(error) });
    const user = userEvent.setup();
    open(control);
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(words);
    expect(screen.getByRole("button", { name: /^Mic/ })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not send a silent or a tiny clip to the engine", async () => {
    for (const [clip, words] of [
      [{ seconds: 2, peak: 0.0005 }, /Nothing could be heard/],
      [{ seconds: 0.1, peak: 0.5 }, /too short/],
    ] as const) {
      const { control, transcribe } = fakeMic({}, clip);
      const user = userEvent.setup();
      const view = render(
        <Screen
          runs={runs()}
          assistant={assistant}
          images={images}
          composerOptions={{ mic: control }}
        />,
      );
      await user.click(screen.getByRole("button", { name: /^Mic/ }));
      await user.click(await screen.findByRole("button", { name: /^Stop/ }));
      expect(await screen.findByRole("alert")).toHaveTextContent(words);
      expect(transcribe).not.toHaveBeenCalled();
      view.unmount();
    }
  });

  it("says what the engine said when it cannot write the clip down", async () => {
    const { control } = fakeMic({
      transcribe: async () =>
        Promise.reject(new Error("The speech model is busy. Try again in a moment.")),
    });
    const user = userEvent.setup();
    open(control);
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    await user.click(await screen.findByRole("button", { name: /^Stop/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The speech model is busy");
    expect(box()).toHaveValue("");
  });

  it("says when no words were caught", async () => {
    const { control } = fakeMic({ transcribe: async () => ({ text: "  " }) });
    const user = userEvent.setup();
    open(control);
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    await user.click(await screen.findByRole("button", { name: /^Stop/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No words were caught");
  });

  it("says when the chat model was put away to make room", async () => {
    const { control } = fakeMic({ transcribe: async () => ({ text: "hi", displaced: "chat" }) });
    const user = userEvent.setup();
    open(control);
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    await user.click(await screen.findByRole("button", { name: /^Stop/ }));
    await waitFor(() => expect(box()).toHaveValue("hi"));
    expect(await screen.findByText(/chat model was put away/)).toBeInTheDocument();
  });

  it("shows the setup card instead of recording when there is no speech model, and sets it up on one click", async () => {
    function Harness() {
      const [ready, setReady] = useState(false);
      const { control } = fakeMic(
        ready
          ? {}
          : {
              setup: {
                title: "Parakeet TDT 0.6B v3",
                licence: "CC-BY-4.0",
                from: "huggingface.co",
                bytes: 955_000_000,
                run: async (onProgress) => {
                  onProgress(0.5);
                  setReady(true);
                },
              },
            },
      );
      return (
        <Screen
          runs={runs()}
          assistant={assistant}
          images={images}
          composerOptions={{ mic: control }}
        />
      );
    }
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    const card = await screen.findByRole("region", { name: "Set up dictation" });
    expect(card).toHaveTextContent("Parakeet TDT 0.6B v3");
    expect(card).toHaveTextContent("CC-BY-4.0");
    expect(card).toHaveTextContent("huggingface.co");
    expect(card).toHaveTextContent("955 MB");
    expect(screen.queryByText(/Listening/)).toBeNull(); // nothing was recorded
    await user.click(within(card).getByRole("button", { name: /^Download/ }));
    expect(await screen.findByText("Dictation is ready. Press Mic to start.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    expect(await screen.findByText(/Listening with/)).toBeInTheDocument();
  });

  it("can decline the setup, and says in words when it fails", async () => {
    const { control } = fakeMic({
      setup: {
        title: "Parakeet",
        licence: "CC-BY-4.0",
        from: "",
        bytes: 1e9,
        run: async () => Promise.reject(new Error("There is not enough disk space.")),
      },
    });
    const user = userEvent.setup();
    open(control);
    await user.click(screen.getByRole("button", { name: /^Mic/ }));
    await user.click(await screen.findByRole("button", { name: /^Download/ }));
    expect(await screen.findByText("There is not enough disk space.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByRole("region", { name: "Set up dictation" })).toBeNull();
  });
});
