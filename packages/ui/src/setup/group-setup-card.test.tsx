import { cleanup, fireEvent, render, screen } from "@testing-library/react";
// @vitest-environment jsdom
// A menu group's one setup card (ADR-0109, stage FR3): what it says on a big and a small computer, with a key first,
// while it runs and when it failed.
import type { SetupGroup, SetupPart } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GroupSetupCard } from "./GroupSetupCard";
import { primaryLabel, whyLine } from "./words";

const GB = 1e9;

const part = (over: Partial<SetupPart>): SetupPart => ({
  id: "component:audiocpp",
  kind: "component",
  ref: "audiocpp",
  title: "Speech runtime (audio.cpp)",
  bytes: 42e6,
  set_up: false,
  installing: false,
  memory_bytes: null,
  available: true,
  reason: "",
  fit: "include",
  included: true,
  items: ["voice.speak"],
  ...over,
});

const ITEMS = [
  "voice.speak",
  "voice.transcribe",
  "voice.voices",
  "voice.convert",
  "voice.edit",
  "voice.dub",
  "voice.audiobook",
];

function voice(over: Partial<SetupGroup> = {}): SetupGroup {
  return {
    id: "voice",
    items: ITEMS.map((id) => ({ id, parts: [], state: "needs_setup" })),
    parts: [
      part({}),
      part({
        id: "model:kokoro-82m",
        kind: "model",
        ref: "kokoro-82m",
        title: "Kokoro 82M",
        bytes: 0.19 * GB,
        memory_bytes: 1 * GB,
      }),
      part({
        id: "model:dots-tts-edit",
        kind: "model",
        ref: "dots-tts-edit",
        title: "dots TTS edit",
        bytes: 2.96 * GB,
        memory_bytes: 7 * GB,
      }),
    ],
    uses: [],
    explain_only: false,
    state: "needs_setup",
    download_bytes: 9 * GB,
    download_instead_bytes: 9 * GB,
    key: { covers: false, first: false, only: false },
    memory_bytes: 64 * GB,
    ...over,
  };
}

const noop = () => {};

afterEach(cleanup);

describe("the words", () => {
  it("sets up every item of a group on a big computer", () => {
    expect(whyLine(voice())).toBe(
      "Sets up everything the 7 tools of Voice need. Runs on this computer, privately.",
    );
    expect(primaryLabel(voice(), null)).toBe("Set up Voice · 9.0 GB");
  });

  it("names what a small computer leaves out", () => {
    const g = voice({ memory_bytes: 8 * GB });
    g.items = g.items.map((i) => (i.id === "voice.edit" ? { ...i, state: "left_out" } : i));
    expect(whyLine(g)).toBe(
      "Voice: 6 of 7 ready on this computer. Edit speech needs a bigger computer.",
    );
  });

  it("says a key is recommended when the model takes most of the memory", () => {
    const g = voice({
      id: "video",
      items: [{ id: "video.create", parts: [], state: "needs_setup" }],
      parts: [part({ kind: "model", memory_bytes: 14 * GB, id: "model:ltx", ref: "ltx" })],
      key: { covers: true, first: true, only: false },
      memory_bytes: 24 * GB,
    });
    expect(whyLine(g)).toMatch(/needs about 14 GB of memory, most of this computer's 24 GB/);
    expect(primaryLabel(g, null)).toBe("Use an API key");
  });

  it("names Creative Studio's groups on its button", () => {
    const g = voice({ id: "creative", uses: ["video", "voice"], download_bytes: 26.1 * GB });
    expect(primaryLabel(g, null)).toBe("Set up Creative Studio, Video and Voice · 26 GB");
  });

  it("counts the chat model when the group needs one", () => {
    const g = voice({
      id: "notebook",
      download_bytes: 1.5 * GB,
      parts: [part({ id: "chat", kind: "chat", ref: "", title: "Chat model", bytes: 0 })],
    });
    expect(primaryLabel(g, 2.5 * GB)).toBe("Set up Notebook · 4.0 GB");
  });
});

describe("the card", () => {
  it("downloads the group with one click", () => {
    const onSetUp = vi.fn();
    render(
      <GroupSetupCard
        group={voice()}
        run={{ state: "idle" }}
        onSetUp={onSetUp}
        onKey={noop}
        onStop={noop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Set up Voice · 9.0 GB" }));
    expect(onSetUp).toHaveBeenCalledWith(false);
    expect(screen.getByRole("heading", { name: "Get started with Voice" })).toBeTruthy();
  });

  it("offers the key first, and the download instead", () => {
    const onKey = vi.fn();
    const onSetUp = vi.fn();
    const g = voice({
      id: "lipsync",
      items: [{ id: "voice.lipsync", parts: [], state: "needs_setup" }],
      parts: [part({ kind: "model", memory_bytes: 12 * GB, title: "MuseTalk 1.5" })],
      key: { covers: true, first: true, only: false },
      memory_bytes: 16 * GB,
      download_bytes: 6.3 * GB,
      download_instead_bytes: 6.3 * GB,
    });
    render(
      <GroupSetupCard
        group={g}
        run={{ state: "idle" }}
        onSetUp={onSetUp}
        onKey={onKey}
        onStop={noop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Use an API key" }));
    expect(onKey).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Download instead · 6.3 GB" }));
    expect(onSetUp).toHaveBeenCalledWith(true);
    expect(screen.getByText("not needed with a key")).toBeTruthy();
  });

  it("offers no download when the computer cannot run it", () => {
    const g = voice({ key: { covers: true, first: true, only: true }, memory_bytes: 8 * GB });
    render(
      <GroupSetupCard
        group={g}
        run={{ state: "idle" }}
        onSetUp={noop}
        onKey={noop}
        onStop={noop}
      />,
    );
    expect(screen.queryByRole("button", { name: /Download instead/ })).toBeNull();
  });

  it("shows the progress and can stop", () => {
    const onStop = vi.fn();
    render(
      <GroupSetupCard
        group={voice()}
        run={{ state: "running", label: "Downloading Kokoro 82M", fraction: 0.4 }}
        onSetUp={noop}
        onKey={noop}
        onStop={onStop}
      />,
    );
    expect(screen.getByText("Downloading Kokoro 82M")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Set up Voice/ })).toBeNull();
  });

  it("says what failed and lets the person carry on", () => {
    render(
      <GroupSetupCard
        group={voice()}
        run={{ state: "failed", message: "The download failed." }}
        onSetUp={noop}
        onKey={noop}
        onStop={noop}
      />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/The download failed/);
    expect(screen.getByRole("button", { name: "Set up Voice · 9.0 GB" })).toBeTruthy();
  });

  it("ticks what is set up already", () => {
    const g = voice();
    g.parts = g.parts.map((p) => (p.ref === "audiocpp" ? { ...p, set_up: true } : p));
    render(
      <GroupSetupCard
        group={g}
        run={{ state: "idle" }}
        onSetUp={noop}
        onKey={noop}
        onStop={noop}
      />,
    );
    expect(screen.getByText("✓ set up")).toBeTruthy();
  });
});
