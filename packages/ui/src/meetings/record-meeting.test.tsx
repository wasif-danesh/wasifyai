// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Meeting, MeetingsApi, MeetingsStatus } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  type MeetingRecorder,
  RecordMeeting,
  type RecordState,
  type RecordedMeeting,
  meter,
} from "./RecordMeeting";

const parakeet = { id: "parakeet", title: "Parakeet", languages: ["en", "de"] };

const status = (over: Partial<MeetingsStatus> = {}): MeetingsStatus => ({
  speaker_model: true,
  speaker_model_id: "sortformer-4spk-v2.1",
  speech: true,
  speech_model: { id: parakeet.id, title: parakeet.title },
  speech_problem: null,
  speech_models: [parakeet],
  busy: false,
  active: null,
  converter: true,
  formats: [".wav"],
  recordings: [],
  voiceprint_model: true,
  voiceprint_model_id: "eres2net-voxceleb",
  ...over,
});

const made = { id: "0b7c1f9e000040008000000000000000", status: "working" } as Meeting;

const api = (over: Partial<MeetingsApi> = {}): MeetingsApi =>
  ({
    status: vi.fn(async () => status()),
    fromRecording: vi.fn(async () => made),
    discardRecording: vi.fn(async () => undefined),
    ...over,
  }) as unknown as MeetingsApi;

const idle: RecordState = {
  others_supported: true,
  recording: false,
  name: null,
  seconds: 0,
  levels: [0, 0],
  mic: false,
  others: false,
  problems: [],
};
const live: RecordState = {
  ...idle,
  recording: true,
  name: "rec-1-ab.wav",
  seconds: 75,
  levels: [0.05, 0.001],
  mic: true,
  others: true,
};
const done: RecordedMeeting = { name: "rec-1-ab.wav", seconds: 75, others: true, problems: [] };

function fakeRecorder(over: Partial<MeetingRecorder> = {}) {
  let told: ((r: RecordedMeeting) => void) | null = null;
  let now = idle;
  const r: MeetingRecorder = {
    state: vi.fn(async () => now),
    start: vi.fn(async () => {
      now = live;
      return live;
    }),
    stop: vi.fn(async () => {
      now = idle;
      return done;
    }),
    onRecorded: (t) => {
      told = t;
      return () => {
        told = null;
      };
    },
    onFailed: () => () => {},
    ...over,
  };
  return { r, stopFromMenu: (x: RecordedMeeting) => told?.(x) };
}

afterEach(() => vi.useRealTimers());

describe("RecordMeeting", () => {
  it("starts, shows the time and both sides, stops and opens the meeting being made", async () => {
    const a = api();
    const { r } = fakeRecorder();
    const onOpen = vi.fn();
    render(<RecordMeeting api={a} recorder={r} onOpen={onOpen} />);
    await userEvent.click(await screen.findByRole("button", { name: /Start recording/ }));
    expect(await screen.findByText("1:15")).toBeInTheDocument();
    const rec = screen.getByRole("region", { name: "Recording" });
    expect(within(rec).getByRole("meter", { name: "You: how loud" })).toHaveAttribute(
      "aria-valuenow",
      String(Math.round(meter(0.05) * 100)),
    );
    expect(within(rec).getByRole("meter", { name: "Others: how loud" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Stop/ }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(made.id));
    expect(a.fromRecording).toHaveBeenCalledWith("rec-1-ab.wav", undefined);
  });

  it("says in words when the microphone or the computer's sound is not heard", async () => {
    const { r } = fakeRecorder({
      state: vi.fn(async () => ({
        ...live,
        mic: false,
        others: false,
        problems: ["The microphone gives no sound: allow Wasify AI to use it."],
      })),
    });
    render(<RecordMeeting api={api()} recorder={r} onOpen={vi.fn()} />);
    expect(await screen.findByText(/microphone gives no sound/)).toBeInTheDocument();
    expect(screen.getByText("not heard")).toBeInTheDocument();
    expect(screen.getByText("not allowed")).toBeInTheDocument();
  });

  it("makes the meeting when Stop is pressed in the menu bar, with the chosen language", async () => {
    const a = api();
    const { r, stopFromMenu } = fakeRecorder();
    const onOpen = vi.fn();
    render(<RecordMeeting api={a} recorder={r} onOpen={onOpen} />);
    await screen.findByRole("button", { name: /Start recording/ });
    await userEvent.click(screen.getByRole("combobox", { name: "Language of the meeting" }));
    await userEvent.click(await screen.findByRole("option", { name: /^German/ }));
    act(() => stopFromMenu(done));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(made.id));
    expect(a.fromRecording).toHaveBeenCalledWith("rec-1-ab.wav", { language: "de" });
  });

  it("keeps a recording that could not be made into a meeting, and offers it again", async () => {
    let calls = 0;
    const waiting = {
      name: "rec-1-ab.wav",
      bytes: 4_800_044,
      seconds: 75,
      modified: 1_763_300_000,
    };
    const a = api({
      status: vi.fn(async () => status(calls++ ? { recordings: [waiting] } : {})),
      fromRecording: vi.fn(async () => {
        throw new Error("Get the speaker model first (about 490 MB, in Models).");
      }),
    });
    const { r } = fakeRecorder();
    render(<RecordMeeting api={a} recorder={r} onOpen={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /Start recording/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop/ }));
    expect(await screen.findByText(/Get the speaker model first/)).toBeInTheDocument();
    const list = await screen.findByRole("region", { name: "Recordings waiting" });
    expect(within(list).getByText("1:15")).toBeInTheDocument();
    await userEvent.click(within(list).getByRole("button", { name: /Throw away/ }));
    // jsdom has no showModal: the dialog's buttons are reached with `hidden`
    const box = await waitFor(() => {
      const d = document.querySelector("dialog");
      if (!d) throw new Error("no dialog");
      return d;
    });
    await userEvent.click(within(box).getByRole("button", { name: "Throw away", hidden: true }));
    await waitFor(() => expect(a.discardRecording).toHaveBeenCalledWith("rec-1-ab.wav"));
  });

  it("says when only the microphone can be recorded here", async () => {
    const { r } = fakeRecorder({
      state: vi.fn(async () => ({ ...idle, others_supported: false })),
    });
    render(<RecordMeeting api={api()} recorder={r} onOpen={vi.fn()} />);
    expect(await screen.findByText("Only your microphone")).toBeInTheDocument();
  });

  it("maps loudness to a meter: silence empty, full scale full", () => {
    expect(meter(0)).toBe(0);
    expect(meter(1)).toBe(1);
    expect(meter(0.001)).toBe(0);
    expect(meter(0.03)).toBeGreaterThan(0.4);
  });
});
