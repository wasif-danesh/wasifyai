// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ParsedEvent, SavedVoice, VoiceApi, VoiceModelInfo } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { AudiobookWorkspace } from "./AudiobookWorkspace";
import { trackKind } from "./TrackList";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

const kokoro = {
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
  licence_evidence: "https://example.test",
  reviewed: "2026-10-16",
  measured: { platform: "darwin-arm64", speed_x: 8.6, memory_gb: null, load_s: null },
  voices: [
    { id: "af_heart", label: "Heart", language: "en-us", gender: "female" },
    { id: "am_adam", label: "Adam", language: "en-us", gender: "male" },
  ],
  default_voice: "af_heart",
  options: [
    {
      name: "speed",
      type: "float",
      label: "Speed",
      description: "",
      default: 1,
      min: 0.5,
      max: 2,
      values: [],
    },
  ],
  music: {},
  state: "ready",
  files_ready: true,
  runtime_ready: true,
  bytes_missing: 0,
} as unknown as VoiceModelInfo;
const designer = {
  ...kokoro,
  id: "qwen3-tts-1.7b-voicedesign",
  title: "Qwen3-TTS VoiceDesign",
  tasks: ["design"],
  recommended: ["design"],
  voices: [],
  options: [],
} as unknown as VoiceModelInfo;

const plan = {
  chapters: [
    { title: "The Storm", text: "The sea was black that night.", chars: 29, estimated_seconds: 2 },
    { title: "The Boat", text: "At dawn a small boat appeared.", chars: 30, estimated_seconds: 2 },
    { title: "The Letter", text: "Inside lay a letter.", chars: 20, estimated_seconds: 2 },
  ],
  chars: 79,
  estimated_seconds: 6,
};

function api(over: Record<string, unknown> = {}): VoiceApi {
  return {
    runtime: vi.fn(async () => ({
      installed: true,
      install: { state: "idle", step: null, message: "", done_bytes: 0, total_bytes: 0 },
    })),
    models: vi.fn(async (task?: string) => (task === "design" ? [designer] : [kokoro])),
    voices: vi.fn(async () => []),
    planBook: vi.fn(async () => plan),
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
    seconds: 12,
    tracks: [
      {
        track_id: "c1",
        title: "B - 1. The Storm",
        seconds: 6,
        audio_url: "http://x/1.wav",
        chapter: 1,
      },
      {
        track_id: "c3",
        title: "B - 3. The Letter",
        seconds: 6,
        audio_url: "http://x/3.wav",
        chapter: 3,
      },
    ],
    book: null,
  },
});

async function planBook(title = "The Lighthouse") {
  await userEvent.type(await screen.findByLabelText("Title of the book"), title);
  await userEvent.type(screen.getByLabelText("The text"), "# The Storm\nThe sea was black.");
  await userEvent.click(screen.getByRole("button", { name: "Find the chapters" }));
  await screen.findByLabelText("Title of chapter 1");
}

const make = () =>
  screen.getByRole("button", { name: /Make the audiobook|Making the book/ }) as HTMLButtonElement;

describe("making an audiobook", () => {
  it("plans the chapters from the text, and shows them before anything is spoken", async () => {
    const a = api();
    render(<AudiobookWorkspace api={a} runs={runsThat([])} />);
    expect(
      ((await screen.findByRole("button", { name: "Find the chapters" })) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await planBook();
    expect(a.planBook).toHaveBeenCalledWith("# The Storm\nThe sea was black.");
    expect((screen.getByLabelText("Title of chapter 2") as HTMLInputElement).value).toBe(
      "The Boat",
    );
    expect(screen.getByText(/3\)|\(3,/)).toBeTruthy();
    expect(make().disabled).toBe(false);
  });

  it("sends the chapters as the person changed them, with the voice and the settings", async () => {
    const runs = runsThat([ev("node", { label: "Chapter 1 of 2, part 1 of 3" }), finished]);
    render(<AudiobookWorkspace api={api()} runs={runs} />);
    await planBook();
    await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[1] as HTMLElement); // the second
    const t = screen.getByLabelText("Title of chapter 1");
    await userEvent.clear(t);
    await userEvent.type(t, "The Great Storm");
    await userEvent.selectOptions(screen.getByLabelText("Voice"), "am_adam");
    await userEvent.click(screen.getByRole("checkbox", { name: /Say each chapter's title/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /one track of the whole book/ }));
    await userEvent.click(make());
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toEqual({
      task: "audiobook",
      title: "The Lighthouse",
      chapters: [
        { title: "The Great Storm", text: "The sea was black that night." },
        { title: "The Letter", text: "Inside lay a letter." },
      ],
      voice: "am_adam",
      model: "kokoro-82m",
      whole: true,
      read_titles: false,
    });
    const done = await screen.findByRole("region", { name: "The audiobook" });
    expect(done.textContent).toContain("2 chapters kept in Your music");
    expect(done.textContent).toContain("B - 3. The Letter");
  });

  it("joins a chapter with the next one, saying the next title as part of the words", async () => {
    const runs = runsThat([finished]);
    render(<AudiobookWorkspace api={api()} runs={runs} />);
    await planBook();
    await userEvent.click(
      screen.getAllByRole("button", { name: "Join with next" })[0] as HTMLElement,
    );
    expect(screen.queryByLabelText("Title of chapter 3")).toBeNull();
    await userEvent.click(make());
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    const sent = runs.startRun.mock.calls[0]?.[1] as {
      chapters: { title: string; text: string }[];
    };
    expect(sent.chapters).toHaveLength(2);
    expect(sent.chapters[0]?.text).toBe(
      "The sea was black that night.\n\nThe Boat.\n\nAt dawn a small boat appeared.",
    );
  });

  it("uses a saved voice with the model that does it", async () => {
    const saved = {
      id: "v1",
      name: "Narrator",
      kind: "design",
      consent: {},
    } as unknown as SavedVoice;
    const runs = runsThat([finished]);
    render(<AudiobookWorkspace api={api({ voices: vi.fn(async () => [saved]) })} runs={runs} />);
    await planBook();
    await userEvent.click(screen.getByRole("radio", { name: "A voice I saved" }));
    expect(make().disabled).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText("Saved voice"), "v1");
    expect(make().disabled).toBe(false);
    await userEvent.click(make());
    await waitFor(() => expect(runs.startRun).toHaveBeenCalled());
    expect(runs.startRun.mock.calls[0]?.[1]).toMatchObject({
      saved_voice: "v1",
      model: "qwen3-tts-1.7b-voicedesign",
    });
    expect((runs.startRun.mock.calls[0]?.[1] as Record<string, unknown>).voice).toBeUndefined();
  });

  it("will not make a whole-book track of a very long book, and says so", async () => {
    const text = "x".repeat(60_000);
    const long = {
      ...plan,
      chapters: [0, 1].map((i) => ({
        title: `Long ${i}`,
        text,
        chars: text.length,
        estimated_seconds: 1,
      })),
    };
    render(
      <AudiobookWorkspace api={api({ planBook: vi.fn(async () => long) })} runs={runsThat([])} />,
    );
    await planBook();
    const box = screen.getByRole("checkbox", {
      name: /one track of the whole book/,
    }) as HTMLInputElement;
    expect(box.disabled).toBe(true);
    expect(screen.getByText(/only for books up to about two hours/)).toBeTruthy();
  });

  it("says in words when the chapters cannot be found or the book cannot be made", async () => {
    const a = api({
      planBook: vi.fn(async () => {
        throw new Error("Paste or open the text of the book first.");
      }),
    });
    const { unmount } = render(<AudiobookWorkspace api={a} runs={runsThat([])} />);
    await userEvent.type(await screen.findByLabelText("The text"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Find the chapters" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Paste or open");
    unmount();
    const failing = runsThat([
      ev("error", {
        code: "engine_stopped",
        message: "The speech runtime stopped. Chapters 1 to 1 were kept in Your music.",
      }),
    ]);
    render(<AudiobookWorkspace api={api()} runs={failing} />);
    await planBook();
    await userEvent.click(make());
    expect((await screen.findByRole("alert")).textContent).toContain("were kept in Your music");
  });

  it("names the tracks a book makes in Your music", () => {
    const t = (mode: string, edit: object) => ({ mode, edit }) as never;
    expect(trackKind(t("chapter", { chapter: 2, of: 9 }))).toBe("chapter 2 of 9");
    expect(trackKind(t("audiobook", {}))).toBe("audiobook");
    expect(trackKind(t("dubbed", { language: "es" }))).toBe("dubbed into es");
  });
});
