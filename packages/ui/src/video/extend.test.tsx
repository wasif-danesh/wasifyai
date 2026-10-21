// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type VideoSummary, type VideosApi, createRunClient } from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { done, node, sse } from "../test-utils";
import { VideoWorkspace } from "./VideoWorkspace";

const fetchMock = vi.fn();
const client = createRunClient({ fetch: (path, init) => fetchMock(path, init) });

beforeEach(() => {
  fetchMock.mockReset();
  sessionStorage.clear();
});

function clip(over: Partial<VideoSummary> = {}): VideoSummary {
  return {
    id: "v1",
    prompt: "A red fox walks through the snow",
    mode: "text",
    status: "done",
    seconds: 2,
    created_at: new Date().toISOString(),
    width: 768,
    height: 512,
    error: null,
    video_url: "http://127.0.0.1:1/files/v1.mp4",
    poster_url: "http://127.0.0.1:1/files/v1.jpg",
    ...over,
  };
}

function api(videos: VideoSummary[], over: Partial<VideosApi> = {}) {
  return {
    list: vi.fn().mockResolvedValue({ videos, next_before: null }),
    exportCopy: vi.fn().mockResolvedValue({ name: "fox.mp4", path: "/Downloads/fox.mp4" }),
    ...over,
  };
}

const ready = done({
  status: "done",
  video_id: "v2",
  video_url: "http://127.0.0.1:1/files/v2.mp4",
  poster_url: "http://127.0.0.1:1/files/v2.jpg",
  width: 768,
  height: 512,
  seconds: 4,
  prompt: "the fox keeps walking",
  mode: "extend",
});

describe("Extend video", () => {
  it("asks for the finished clips and shows only the ones that can be carried on", async () => {
    const videos = api([
      clip(),
      clip({ id: "v3", prompt: "Waves on a beach", seconds: 4 }),
      clip({ id: "v9", prompt: "A long walk", seconds: 5 }),
    ]);
    render(<VideoWorkspace mode="extend" runs={client} videos={videos} />);
    expect(await screen.findByRole("button", { name: /red fox walks/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /waves on a beach/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /a long walk/i })).not.toBeInTheDocument();
    expect(videos.list).toHaveBeenCalledWith(expect.objectContaining({ status: "done" }));
    expect(screen.getByText(/longer than about 4 seconds are not shown/i)).toBeInTheDocument();
  });

  it("fills in the words from the chosen clip, keeps the person's own words, and sends the clip's id", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), node("generate_video"), ready]));
    const user = userEvent.setup();
    render(
      <VideoWorkspace
        mode="extend"
        runs={client}
        videos={api([clip(), clip({ id: "v3", prompt: "Waves on a beach", seconds: 4 })])}
        canSave
      />,
    );
    const make = screen.getByRole("button", { name: /carry on my video/i });
    expect(make).toBeDisabled(); // nothing chosen yet
    await user.click(await screen.findByRole("button", { name: /red fox walks/i }));
    const words = screen.getByRole("textbox");
    expect(words).toHaveValue("A red fox walks through the snow");
    await user.clear(words);
    await user.type(words, "the fox keeps walking");
    await user.click(screen.getByRole("button", { name: /waves on a beach/i }));
    expect(words).toHaveValue("the fox keeps walking"); // what the person typed stays
    await user.click(screen.getByRole("button", { name: /red fox walks/i }));
    expect(make).toBeEnabled();
    await user.click(make);

    expect(await screen.findByText(/saved in your videos/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/products/wasifyai-video/runs");
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body.input).toEqual({
      mode: "extend",
      prompt: "the fox keeps walking",
      source_id: "v1",
    });
    expect(document.querySelector("video")).toHaveAttribute(
      "src",
      "http://127.0.0.1:1/files/v2.mp4",
    );
    expect(screen.getByText(/your video, carried on/i)).toBeInTheDocument();
  });

  it("says so when there is nothing to carry on, and when the list cannot be loaded", async () => {
    const empty = render(<VideoWorkspace mode="extend" runs={client} videos={api([])} />);
    expect(await screen.findByText(/no videos to carry on yet/i)).toBeInTheDocument();
    empty.unmount();

    const list = vi
      .fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce({ videos: [clip()], next_before: null });
    const user = userEvent.setup();
    render(<VideoWorkspace mode="extend" runs={client} videos={api([], { list })} />);
    const alert = await screen.findByText(/could not be loaded/i);
    const box = alert.closest("div") as HTMLElement;
    await user.click(within(box.parentElement ?? box).getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("button", { name: /red fox walks/i })).toBeInTheDocument();
  });

  it("shows a refusal from the engine in words and brings the form back", async () => {
    fetchMock.mockResolvedValueOnce(
      sse([
        node("check_request"),
        done({
          status: "refused",
          refusal: { code: "clip_too_long", message: "This video is as long as it can get." },
        }),
      ]),
    );
    const user = userEvent.setup();
    render(<VideoWorkspace mode="extend" runs={client} videos={api([clip()])} />);
    await user.click(await screen.findByRole("button", { name: /red fox walks/i }));
    await user.click(screen.getByRole("button", { name: /carry on my video/i }));
    expect(await screen.findByText(/as long as it can get/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /carry on my video/i })).toBeInTheDocument();
  });
});
