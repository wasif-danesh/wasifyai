import { STARTED_EVENT } from "@/hooks/use-video-activity";
import { webCreationsNav } from "@/lib/creations-nav";
import { webCreations } from "@/lib/library";
// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { VideoSummary } from "@wasifyai/client";
import { CreationsList } from "@wasifyai/ui";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VideoLibraryScreen, VideoScreen } from "./VideoScreens";
import { VideoView } from "./VideoView";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  usePathname: () => "/video",
}));

const fetchMock = vi.fn();
beforeEach(() => {
  sessionStorage.clear(); // a run left open by one test must not be restored by the next
  fetchMock.mockReset();
  push.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

const png = () => new File([new Uint8Array(10)], "a.png", { type: "image/png" });

const clip = (over: Partial<VideoSummary> = {}): VideoSummary => ({
  id: "00000000-0000-0000-0000-000000000001",
  prompt: "a red fox",
  mode: "text",
  status: "done",
  seconds: 2,
  created_at: "2026-10-08T00:00:00Z",
  width: 768,
  height: 512,
  error: null,
  video_url: "http://x/v.mp4",
  poster_url: "http://x/p.jpg",
  ...over,
});

describe("VideoScreen (the web app's mount of the shared screen)", () => {
  it("goes through the BFF, tells the header and offers the download", async () => {
    const user = userEvent.setup();
    const events = [
      ["node", { node: "generate_video", status: "started", label: "Making your video" }],
      [
        "done",
        {
          outputs: {
            status: "done",
            video_id: "v9",
            video_url: "http://x/v9.mp4",
            poster_url: "http://x/v9.jpg",
            width: 768,
            height: 512,
            seconds: 2,
            prompt: "a red fox",
            mode: "text",
          },
        },
      ],
    ] as const;
    const body = events
      .map(
        ([name, data], i) =>
          `id: ${i + 1}\nevent: ${name}\ndata: ${JSON.stringify({ run_id: "r", thread_id: "t", seq: i + 1, ts: "", ...data })}\n\n`,
      )
      .join("");
    fetchMock.mockResolvedValueOnce(
      new Response(body, { headers: { "content-type": "text/event-stream" } }),
    );
    render(<VideoScreen mode="text" />);
    await user.type(screen.getByRole("textbox"), "a red fox");
    await user.click(screen.getByRole("button", { name: /make my video/i }));
    expect(await screen.findByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-video/videos/v9/download",
    );
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/products/wasifyai-video/runs");
    await user.click(screen.getByRole("button", { name: /your videos/i }));
    expect(push).toHaveBeenCalledWith("/video/library");
  });

  it("tells the header at once when a clip starts being made", async () => {
    const user = userEvent.setup();
    const started = vi.fn();
    window.addEventListener(STARTED_EVENT, started);
    const frame = `id: 1\nevent: node\ndata: ${JSON.stringify({ run_id: "r", thread_id: "t", seq: 1, ts: "", node: "generate_video", status: "started", label: "Making your video" })}\n\n`;
    fetchMock.mockResolvedValueOnce(
      new Response(
        new ReadableStream({
          start(c) {
            c.enqueue(new TextEncoder().encode(frame)); // the job goes on: the stream stays open
          },
        }),
        { headers: { "content-type": "text/event-stream" } },
      ),
    );
    render(<VideoScreen mode="text" />);
    await user.type(screen.getByRole("textbox"), "a red fox");
    await user.click(screen.getByRole("button", { name: /make my video/i }));
    await waitFor(() => expect(started).toHaveBeenCalled());
    window.removeEventListener(STARTED_EVENT, started);
  });

  it("says what each mode is for and tells how long a clip takes here", () => {
    render(<VideoScreen mode="image" />);
    expect(screen.getByRole("heading", { name: "Animate a picture" })).toBeInTheDocument();
    expect(screen.getByText(/The clip keeps the shape of your picture/)).toBeInTheDocument();
  });
});

describe("VideoLibraryScreen", () => {
  it("lists clips with a download link", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(Response.json({ videos: [clip()], next_before: null }));
    render(<VideoLibraryScreen />);
    await user.click(await screen.findByRole("button", { name: /open: a red fox/i }));
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-video/videos/00000000-0000-0000-0000-000000000001/download",
    );
  });
});

describe("VideoView", () => {
  it("plays a finished clip, offers the download and asks twice before deleting", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const user = userEvent.setup();
    const { container } = render(<VideoView initial={clip()} />);
    expect(container.querySelector("video")).toHaveAttribute("src", "http://x/v.mp4");
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-video/videos/00000000-0000-0000-0000-000000000001/download",
    );
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /yes, delete/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/creations"));
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "DELETE" });
  });

  it("says a clip is being made, offers no delete, and shows it when it is ready", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValue(Response.json(clip()));
    const { container } = render(
      <VideoView initial={clip({ status: "working", video_url: null, poster_url: null })} />,
    );
    expect(screen.getByText(/your video is being created/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
    await act(async () => void (await vi.advanceTimersByTimeAsync(10_000)));
    expect(container.querySelector("video")).toHaveAttribute("src", "http://x/v.mp4");
    vi.useRealTimers();
  });

  it("explains a failed clip and lets the user remove it", () => {
    render(
      <VideoView
        initial={clip({ status: "failed", error: "It took too long.", video_url: null })}
      />,
    );
    expect(screen.getByText("It took too long.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /download/i })).toBeNull();
  });
});

describe("creations with videos", () => {
  const songs: never[] = [];
  const images = { images: [], next_before: null };

  it("shows clips with their state and filters them", async () => {
    const user = userEvent.setup();
    const videos = {
      videos: [
        clip({ id: "a", prompt: "ready clip", created_at: "2026-10-08T03:00:00Z" }),
        clip({
          id: "b",
          prompt: "busy clip",
          status: "working",
          poster_url: null,
          video_url: null,
          created_at: "2026-10-08T02:00:00Z",
        }),
        clip({
          id: "c",
          prompt: "broken clip",
          status: "failed",
          poster_url: null,
          video_url: null,
          created_at: "2026-10-08T01:00:00Z",
        }),
      ],
      next_before: null,
    };
    render(
      <CreationsList
        api={webCreations}
        nav={webCreationsNav(push)}
        songs={songs}
        images={images}
        videos={videos}
      />,
    );
    expect(screen.getByRole("link", { name: /ready clip/i })).toHaveAttribute(
      "href",
      "/video/creations/a",
    );
    expect(screen.getByText("Making your video…")).toBeInTheDocument();
    expect(screen.getByText("Couldn't be made")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /videos/i }));
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: /music/i }));
    expect(screen.getByText(/no music yet/i)).toBeInTheDocument();
  });

  it("loads more clips from the video list", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({ videos: [clip({ id: "z", prompt: "older clip" })], next_before: null }),
    );
    const user = userEvent.setup();
    render(
      <CreationsList
        api={webCreations}
        nav={webCreationsNav(push)}
        songs={songs}
        images={images}
        videos={{ videos: [clip({ id: "y" })], next_before: "2026-10-07T00:00:00Z" }}
      />,
    );
    await user.click(screen.getByRole("button", { name: /load more/i }));
    await waitFor(() =>
      expect(screen.getByRole("link", { name: /older clip/i })).toBeInTheDocument(),
    );
    expect(fetchMock.mock.calls[0][0]).toContain(
      "/api/products/wasifyai-video/videos?limit=12&before=",
    );
  });
});

describe("searching My creations", () => {
  const songs: never[] = [];
  const images = { images: [], next_before: null };
  const search = (results: object[], degraded = false) =>
    Response.json({ query: "fox", degraded, results });
  const hit = (kind: string, id: string, match = "meaning") => ({
    kind,
    product_id: `wasifyai-${kind}-ai`,
    id,
    score: 0.7,
    match,
  });

  it("shows ranked results in place of the library, says how many, and clears", async () => {
    fetchMock.mockResolvedValueOnce(search([hit("video", "v9", "words")])).mockResolvedValueOnce(
      Response.json({
        videos: [clip({ id: "v9", prompt: "found fox clip" })],
        next_before: null,
      }),
    );
    const user = userEvent.setup();
    render(
      <CreationsList
        api={webCreations}
        nav={webCreationsNav(push)}
        songs={songs}
        images={images}
        videos={{ videos: [clip({ id: "v1", prompt: "library clip" })], next_before: null }}
      />,
    );
    expect(screen.getByText("library clip")).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: /search your creations/i }), "fox");
    expect(await screen.findByText("found fox clip")).toBeInTheDocument();
    expect(screen.queryByText("library clip")).toBeNull();
    expect(screen.getByText(/1 result for/)).toBeInTheDocument();
    expect(screen.getByText("Exact words")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByText("library clip")).toBeInTheDocument();
  });

  it("says plainly when nothing matched, and when only exact words were searched", async () => {
    fetchMock.mockResolvedValueOnce(search([], true));
    const user = userEvent.setup();
    render(
      <CreationsList
        api={webCreations}
        nav={webCreationsNav(push)}
        songs={songs}
        images={images}
        videos={null}
      />,
    );
    await user.type(screen.getByRole("searchbox", { name: /search your creations/i }), "zzzz");
    expect(await screen.findByText(/nothing matched/i)).toBeInTheDocument();
    expect(screen.getByText(/exact word matches only/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /clear the search/i }));
    expect(screen.queryByText(/nothing matched/i)).toBeNull();
  });

  it("asks for the kind that is filtered", async () => {
    fetchMock.mockResolvedValueOnce(search([]));
    const user = userEvent.setup();
    render(
      <CreationsList
        api={webCreations}
        nav={webCreationsNav(push)}
        songs={songs}
        images={images}
        videos={null}
      />,
    );
    await user.click(screen.getByRole("button", { name: /images/i }));
    await user.type(screen.getByRole("searchbox", { name: /search your creations/i }), "fox");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toContain("kind=image");
  });

  it("shows a notice and keeps the library when the search fails", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 429 }));
    const user = userEvent.setup();
    render(
      <CreationsList
        api={webCreations}
        nav={webCreationsNav(push)}
        songs={songs}
        images={images}
        videos={{ videos: [clip({ prompt: "library clip" })], next_before: null }}
      />,
    );
    await user.type(screen.getByRole("searchbox", { name: /search your creations/i }), "fox");
    expect(await screen.findByText(/searched a lot/i)).toBeInTheDocument();
  });
});
