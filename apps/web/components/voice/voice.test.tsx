// @vitest-environment jsdom
import { VOICE_SCREENS, type VoiceScreenName } from "@/lib/voice-screens";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceScreen } from "./VoiceScreen";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/voice" }));

const fetchMock = vi.fn();
beforeEach(() => {
  push.mockReset();
  fetchMock.mockReset();
  localStorage.clear();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const model = (task: string) => ({
  id: `m-${task}`,
  title: `Model for ${task}`,
  licence: "provider terms",
  engine: task === "speak" ? "remote" : "audiocpp",
  family: "x",
  tasks: [task],
  recommended: [task],
  languages: ["en"],
  sample_rate: 24000,
  commercial_use: "yes",
  licence_evidence: "https://example.com",
  reviewed: "2026-10-18",
  measured: { platform: "p", speed_x: null, memory_gb: null, load_s: null },
  voices: [{ id: "alloy", label: "Alloy", language: "en", gender: "female" }],
  default_voice: "alloy",
  options: [],
  music: {},
  state: "ready",
  bytes_missing: 0,
  note: "",
});

function service() {
  fetchMock.mockImplementation(async (path: string) => {
    const url = new URL(path, "http://x");
    if (url.pathname.endsWith("/models")) {
      const task = url.searchParams.get("task") ?? "speak";
      return Response.json({ models: [model(task)] });
    }
    if (url.pathname.endsWith("/runtime")) return Response.json({ hosted: true });
    return Response.json({ items: [] });
  });
}

describe("the web's voice screens", () => {
  it("text to speech asks the product for its models and never the desktop's engine", async () => {
    service();
    render(<VoiceScreen screen="speak" />);
    expect(await screen.findByLabelText("Model")).toHaveTextContent("Model for speak");
    const asked = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(asked.some((p) => p.startsWith("/api/products/wasifyai-voice/models?task=speak"))).toBe(
      true,
    );
    expect(asked.some((p) => p.includes("/desktop/"))).toBe(false);
    expect(screen.getByText(/sends the text to its provider/i)).toBeInTheDocument();
  });

  it("says that a hosted model sends what it is given to its provider", async () => {
    service();
    render(<VoiceScreen screen="speak" />);
    expect(await screen.findByText(/sent to its provider to be processed/i)).toBeInTheDocument();
  });

  it("does not promise that nothing leaves the computer", async () => {
    service();
    render(<VoiceScreen screen="music" />);
    await screen.findByLabelText("Model");
    expect(screen.queryByText(/on this computer/i)).toBeNull();
    expect(screen.queryByText(/nothing leaves/i)).toBeNull();
  });

  it("takes lyrics to Create music on the web's address", async () => {
    service();
    const user = userEvent.setup();
    render(<VoiceScreen screen="tracks" />);
    await user.click(await screen.findByRole("button", { name: "Make something new" }));
    expect(push).toHaveBeenCalledWith("/voice/music");
  });

  it("says why the service cannot answer", async () => {
    fetchMock.mockResolvedValue(
      Response.json({ detail: "Speech is not available in this deployment yet." }, { status: 503 }),
    );
    render(<VoiceScreen screen="speak" />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("has a page for every screen it can offer", () => {
    for (const name of Object.keys(VOICE_SCREENS) as VoiceScreenName[]) {
      service();
      const { unmount } = render(<VoiceScreen screen={name} />);
      expect(document.body.textContent).toBeTruthy();
      unmount();
    }
  });
});
