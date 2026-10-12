// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SpokenLanguages, TranscriptDetail } from "@wasifyai/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TranscribeForm } from "./TranscribeForm";
import { TranscriptView } from "./TranscriptView";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const catalog = {
  max_seconds: 1800,
  max_bytes: 104857600,
  languages: [
    { id: "en", name: "English", english: "English", quality: "good" },
    { id: "bn", name: "বাংলা", english: "Bengali", quality: "limited" },
    { id: "ar", name: "العربية", english: "Arabic", quality: "fair" },
  ],
} as SpokenLanguages;

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() }),
  );
});
afterEach(() => vi.unstubAllGlobals());

const audio = () => new File([new Uint8Array(2000)], "talk.mp3", { type: "audio/mpeg" });
const uploaded = () =>
  Response.json({ upload_id: "u1", key: "uploads/a.wav", seconds: 75, bytes: 99 }, { status: 201 });

async function chooseFile(container: HTMLElement) {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, audio());
}

describe("TranscribeForm", () => {
  it("cannot be sent until a recording has been uploaded", async () => {
    fetchMock.mockResolvedValue(uploaded());
    const onSubmit = vi.fn();
    const { container } = render(<TranscribeForm catalog={catalog} onSubmit={onSubmit} />);
    const go = screen.getByRole("button", { name: "Transcribe" });
    expect(go).toBeDisabled();
    await chooseFile(container);
    expect(await screen.findByText("talk.mp3")).toBeInTheDocument();
    expect(screen.getByText("1:15")).toBeInTheDocument(); // the length the server measured
    expect(go).toBeEnabled();
    await userEvent.click(go);
    expect(onSubmit).toHaveBeenCalledWith({ audioKey: "uploads/a.wav", language: "auto" });
  });

  it("sends the language that was chosen, and warns when it is a weaker one", async () => {
    fetchMock.mockResolvedValue(uploaded());
    const onSubmit = vi.fn();
    const { container } = render(<TranscribeForm catalog={catalog} onSubmit={onSubmit} />);
    await chooseFile(container);
    await screen.findByText("talk.mp3");
    expect(screen.getByText(/listen to the start of the recording/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Language" }));
    await userEvent.click(await screen.findByRole("option", { name: /Bengali/ }));
    expect(screen.getByText(/more mistakes than in most/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    expect(onSubmit).toHaveBeenCalledWith({ audioKey: "uploads/a.wav", language: "bn" });
  });

  it("offers detection first, then every language in its own script", async () => {
    render(<TranscribeForm catalog={catalog} onSubmit={vi.fn()} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Language" }));
    const names = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(names).toEqual(["Detect the language", "English", "বাংলা · Bengali", "العربية · Arabic"]);
  });

  it("shows why a file was refused and sends nothing", async () => {
    fetchMock.mockResolvedValue(
      Response.json({ detail: "That file could not be read as audio." }, { status: 422 }),
    );
    const { container } = render(<TranscribeForm catalog={catalog} onSubmit={vi.fn()} />);
    await chooseFile(container);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read as audio");
    expect(screen.getByRole("button", { name: "Transcribe" })).toBeDisabled();
  });

  it("explains that it needs a secure page when the microphone is not available", async () => {
    vi.stubGlobal("isSecureContext", false);
    render(<TranscribeForm catalog={catalog} onSubmit={vi.fn()} />);
    await userEvent.click(screen.getByRole("tab", { name: "Record" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start recording" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/secure page/);
  });
});

const detail = (over: Partial<TranscriptDetail> = {}): TranscriptDetail => ({
  id: "11111111-1111-1111-1111-111111111111",
  title: "Hello there",
  status: "done",
  language: "en",
  language_name: "English",
  seconds: 3725,
  created_at: "2026-10-09T10:00:00Z",
  preview: "Hello there. How are you?",
  error: null,
  text: "Hello there. How are you?",
  segments: [
    { start: 0, end: 1.5, text: "Hello there." },
    { start: 62, end: 64, text: "How are you?" },
  ],
  ...over,
});

describe("TranscriptView", () => {
  it("shows the words, then the timed lines, and links the four downloads", async () => {
    render(<TranscriptView initial={detail()} />);
    expect(screen.getByRole("heading", { name: "Hello there" })).toBeInTheDocument();
    expect(screen.getByText(/English · 1:02:05/)).toBeInTheDocument();
    expect(screen.getByText("Hello there. How are you?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Timestamps" }));
    expect(screen.getByText("1:02")).toBeInTheDocument();
    expect(screen.getByText("How are you?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Download/ }));
    const hrefs = (await screen.findAllByRole("menuitem")).map((m) => m.getAttribute("href"));
    expect(hrefs).toEqual(
      ["txt", "srt", "vtt", "json"].map(
        (f) =>
          `/api/products/wasifyai-stt/transcripts/11111111-1111-1111-1111-111111111111/download?format=${f}`,
      ),
    );
  });

  it("copies the words", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<TranscriptView initial={detail()} />);
    await userEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("Hello there. How are you?");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("says a recording is still being transcribed and cannot be deleted yet", () => {
    render(
      <TranscriptView initial={detail({ status: "working", text: "", segments: [], title: "" })} />,
    );
    expect(screen.getByText("Your recording is being transcribed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("shows why it failed and lets it be removed", () => {
    render(
      <TranscriptView
        initial={detail({
          status: "failed",
          error: "No speech was found in that recording.",
          text: "",
        })}
      />,
    );
    expect(screen.getByText("No speech was found in that recording.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
  });

  it("checks again while it is being made and shows the result when it is ready", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValue(Response.json(detail()));
    render(<TranscriptView initial={detail({ status: "working", text: "", segments: [] })} />);
    await vi.advanceTimersByTimeAsync(10_000);
    vi.useRealTimers();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Hello there" })).toBeInTheDocument(),
    );
  });
});
