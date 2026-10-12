// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { LipSyncSummary, VoiceCatalog } from "@wasifyai/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CreationsList } from "../creations/CreationsList";
import { LipSyncForm } from "./LipSyncForm";
import { LipSyncView } from "./LipSyncView";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  usePathname: () => "/lip-sync",
}));

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  push.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

const png = () => new File([new Uint8Array(10)], "a.png", { type: "image/png" });
const voice = () => new File([new Uint8Array(10)], "hello.wav", { type: "audio/wav" });

const catalog = {
  languages: [
    {
      id: "en-US",
      name: "English (US)",
      english: "English (US)",
      quality: "good",
      genders: {
        female: [{ id: "af", label: "Ada", default: true, quality: "good" }],
        male: [{ id: "am", label: "Sam", default: true, quality: "good" }],
      },
    },
    {
      id: "bn",
      name: "বাংলা",
      english: "Bengali",
      quality: "fair",
      genders: { female: [{ id: "bf", label: "Rupa", default: true, quality: "fair" }], male: [] },
    },
  ],
} as unknown as VoiceCatalog;

const item = (over: Partial<LipSyncSummary> = {}): LipSyncSummary => ({
  id: "00000000-0000-0000-0000-000000000001",
  text: "Hello there",
  style: "calm",
  source: "script",
  status: "done",
  seconds: 3.5,
  created_at: "2026-10-09T00:00:00Z",
  width: 640,
  height: 640,
  error: null,
  video_url: "http://x/v.mp4",
  poster_url: "http://x/p.jpg",
  ...over,
});

async function pickPicture(user: ReturnType<typeof userEvent.setup>) {
  fetchMock.mockResolvedValueOnce(
    Response.json({ upload_id: "p1", key: "uploads/p1.png", width: 3, height: 2, bytes: 9 }),
  );
  await user.upload(screen.getByLabelText("Your picture"), png());
}

describe("LipSyncForm", () => {
  it("needs a picture and a script, then hands over the picture's key and the script", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup({ applyAccept: false });
    render(<LipSyncForm catalog={catalog} onSubmit={onSubmit} />);
    const go = screen.getByRole("button", { name: /make my lip sync/i });
    expect(go).toBeDisabled();
    await user.type(screen.getByLabelText(/what should the character say/i), "  Hello there ");
    expect(go).toBeDisabled(); // no picture yet
    await pickPicture(user);
    await waitFor(() => expect(go).toBeEnabled());
    await user.type(screen.getByLabelText(/style/i), "calm");
    await user.click(go);
    const value = onSubmit.mock.calls[0][0];
    expect(value).toMatchObject({
      source: "script",
      script: "Hello there",
      language: "en-US",
      gender: "female",
      style: "calm",
    });
    expect(value.picture).toMatchObject({ uploadId: "p1", key: "uploads/p1.png" });
  });

  it("offers only the genders a language has", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<LipSyncForm catalog={catalog} onSubmit={vi.fn()} initial={{ language: "bn" }} />);
    expect(screen.getByRole("button", { name: "Male" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Female" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Female" }));
  });

  it("uses an uploaded voice instead of a script, and says how long it can be", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup({ applyAccept: false });
    render(<LipSyncForm catalog={catalog} onSubmit={onSubmit} />);
    await pickPicture(user);
    await user.click(screen.getByRole("tab", { name: /upload audio/i }));
    expect(screen.getByText(/up to 5 minutes/i)).toBeInTheDocument();
    const go = screen.getByRole("button", { name: /make my lip sync/i });
    expect(go).toBeDisabled();
    fetchMock.mockResolvedValueOnce(
      Response.json({ upload_id: "a1", key: "uploads/a1.wav", seconds: 4, bytes: 9 }),
    );
    await user.upload(screen.getByLabelText("Audio or video file"), voice());
    await waitFor(() => expect(go).toBeEnabled());
    await user.click(go);
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      source: "audio",
      audioKey: "uploads/a1.wav",
    });
  });
});

describe("LipSyncView", () => {
  it("plays a finished lip sync, offers the download and asks twice before deleting", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const user = userEvent.setup();
    const { container } = render(<LipSyncView initial={item()} />);
    expect(container.querySelector("video")).toHaveAttribute("src", "http://x/v.mp4");
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-lipsync/lipsyncs/00000000-0000-0000-0000-000000000001/download",
    );
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /yes, delete/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/creations"));
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "DELETE" });
  });

  it("says it is being made, offers no delete, and shows it when it is ready", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValue(Response.json(item()));
    const { container } = render(
      <LipSyncView initial={item({ status: "working", video_url: null, poster_url: null })} />,
    );
    expect(screen.getByText(/your lip sync is being created/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
    await act(async () => void (await vi.advanceTimersByTimeAsync(10_000)));
    expect(container.querySelector("video")).toHaveAttribute("src", "http://x/v.mp4");
    vi.useRealTimers();
  });

  it("explains a failed lip sync and lets the user remove it", () => {
    render(
      <LipSyncView
        initial={item({ status: "failed", error: "It took too long.", video_url: null })}
      />,
    );
    expect(screen.getByText("It took too long.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^remove$/i })).toBeInTheDocument();
  });
});

describe("lip syncs in My creations", () => {
  it("shows them under their own filter, with the words as the title", async () => {
    const user = userEvent.setup();
    render(
      <CreationsList
        songs={null}
        images={null}
        lipsyncs={{ lipsyncs: [item()], next_before: null }}
      />,
    );
    await user.click(screen.getByRole("button", { name: /lip syncs/i }));
    const link = screen.getByRole("link", { name: /hello there/i });
    expect(link).toHaveAttribute(
      "href",
      "/lip-sync/creations/00000000-0000-0000-0000-000000000001",
    );
  });
});
