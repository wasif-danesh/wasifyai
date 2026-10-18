// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { VoiceApi } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { MusicPage, SpeakPage, ToolPage, TracksPage, VoicesPage } from "./pages";

// the pages' own work: the sentences about where things go, and the hand-offs between screens
const api = {
  models: vi.fn(async () => []),
  runtime: vi.fn(async () => ({ installed: true, install: { state: "ready" } })),
  speeches: vi.fn(async () => []),
  voices: vi.fn(async () => []),
  tracks: vi.fn(async () => []),
  formats: vi.fn(async () => ({ formats: [], default: "wav" })),
} as unknown as VoiceApi;
const runs = { startRun: vi.fn() };

function memory(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial));
  return {
    get: (k: string) => store.get(k) ?? null,
    set: (k: string, v: string) => void store.set(k, v),
  };
}

const props = (place: "device" | "service", go = vi.fn(), remembered = memory()) => ({
  api,
  runs,
  remembered,
  go,
  place,
});

describe("the voice pages", () => {
  it("promise that nothing leaves the computer only on the desktop", () => {
    const { unmount } = render(<SpeakPage {...props("device")} />);
    expect(screen.getByText(/nothing is sent away/i)).toBeInTheDocument();
    unmount();
    render(<SpeakPage {...props("service")} />);
    expect(screen.queryByText(/nothing is sent away/i)).toBeNull();
    expect(screen.getByText(/marked Hosted sends the text to its provider/i)).toBeInTheDocument();
  });

  it("name each tool and say where it runs", () => {
    const { unmount } = render(<ToolPage tool="separate" {...props("device")} />);
    expect(screen.getByRole("heading", { name: "Split into parts" })).toBeInTheDocument();
    expect(screen.getByText(/on this computer/i)).toBeInTheDocument();
    unmount();
    render(<ToolPage tool="convert" {...props("service")} />);
    expect(screen.getByRole("heading", { name: "Change a voice" })).toBeInTheDocument();
    expect(screen.queryByText(/nothing leaves/i)).toBeNull();
  });

  it("do not offer to fetch a model where a person cannot", async () => {
    render(<MusicPage {...props("service")} />);
    expect(await screen.findByRole("heading", { name: "Create music" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /get it in models/i })).toBeNull();
  });

  it("hand a saved voice to Text to speech once", async () => {
    const remembered = memory();
    const go = vi.fn();
    render(<VoicesPage {...props("device", go, remembered)} />);
    expect(await screen.findByRole("heading", { name: "Voices" })).toBeInTheDocument();
    remembered.set("wasifyai.voice.use", "v1");
    render(<SpeakPage {...props("device", go, remembered)} />);
    await screen.findAllByRole("heading", { name: "Text to speech" });
    expect(remembered.get("wasifyai.voice.use")).toBe("");
  });

  it("open Create music from Your music", async () => {
    const go = vi.fn();
    const user = userEvent.setup();
    render(<TracksPage {...props("service", go)} />);
    await user.click(screen.getByRole("button", { name: "Make something new" }));
    expect(go).toHaveBeenCalledWith("music");
  });
});
