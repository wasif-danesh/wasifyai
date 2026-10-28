// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
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
    importVideo: vi.fn(),
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

const make = () => screen.getByRole("button", { name: "Make the video" });
const resultShown = () =>
  waitFor(() =>
    expect(screen.getByRole("region", { name: "Result" })).toHaveAttribute("data-state", "result"),
  );

describe("Extend video", () => {
  it("asks for the finished clips and lists them all in the strip, whatever their length", async () => {
    const videos = api([
      clip(),
      clip({ id: "v3", prompt: "Waves on a beach", seconds: 4 }),
      clip({ id: "v9", prompt: "A long walk", seconds: 8 }),
    ]);
    render(<VideoWorkspace mode="extend" runs={client} videos={videos} />);
    expect(await screen.findByRole("button", { name: /choose: a red fox/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /choose: waves on a beach/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /choose: a long walk/i })).toBeInTheDocument(); // no cap
    expect(videos.list).toHaveBeenCalledWith(expect.objectContaining({ status: "done" }));
  });

  it("asks how much to add, five seconds unless said otherwise, and sends it", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), node("generate_video"), ready]));
    const user = userEvent.setup();
    render(<VideoWorkspace mode="extend" runs={client} videos={api([clip()])} />);
    await user.click(await screen.findByRole("button", { name: /choose: a red fox/i }));
    expect(screen.getByRole("button", { name: /about 5 seconds/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: /about 8 seconds/i }));
    expect(screen.getByText(/two or three rounds is a sensible stop/i)).toBeInTheDocument();
    await user.click(make());
    await resultShown();
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body.input).toMatchObject({ mode: "extend", source_id: "v1", seconds: 8 });
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
    expect(make()).toBeDisabled(); // nothing chosen yet
    await user.click(await screen.findByRole("button", { name: /choose: a red fox/i }));
    const words = screen.getByRole("textbox");
    expect(words).toHaveValue("A red fox walks through the snow");
    await user.clear(words);
    await user.type(words, "the fox keeps walking");
    await user.click(screen.getByRole("button", { name: /choose: waves on a beach/i }));
    expect(words).toHaveValue("the fox keeps walking"); // what the person typed stays
    await user.click(screen.getByRole("button", { name: /choose: a red fox/i }));
    expect(make()).toBeEnabled();
    await user.click(make());

    await resultShown();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/products/wasifyai-video/runs");
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body.input).toEqual({
      mode: "extend",
      prompt: "the fox keeps walking",
      source_id: "v1",
      seconds: 5,
    });
    expect(screen.getByRole("region", { name: "Result" }).querySelector("video")).toHaveAttribute(
      "src",
      "http://127.0.0.1:1/files/v2.mp4",
    );
    expect(screen.getByText(/carried on · 4 s/i)).toBeInTheDocument();
  });

  it("starts from a clip sent from another screen", async () => {
    render(
      <VideoWorkspace
        mode="extend"
        runs={client}
        videos={api([clip()])}
        sourceVideo={clip({ id: "v5", prompt: "A kite in the wind" })}
      />,
    );
    expect(screen.getByRole("textbox")).toHaveValue("A kite in the wind");
    expect(
      within(screen.getByRole("region", { name: "Your video" })).getByText("A kite in the wind"),
    ).toBeInTheDocument();
    expect(make()).toBeEnabled();
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
    await screen.findByText(/could not be loaded/i);
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("button", { name: /choose: a red fox/i })).toBeInTheDocument();
  });

  it("shows a refusal from the engine in words and keeps the choice", async () => {
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
    await user.click(await screen.findByRole("button", { name: /choose: a red fox/i }));
    await user.click(make());
    expect(await screen.findByText(/as long as it can get/i)).toBeInTheDocument();
    expect(make()).toBeEnabled();
  });

  it("adds a video file of the person's own, chooses it, and carries it on whatever its length", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), node("generate_video"), ready]));
    const added = clip({
      id: "v7",
      prompt: "holiday clip",
      mode: "import",
      seconds: 12, // longer than a clip the model made may be
      poster_url: "http://127.0.0.1:1/files/v7.jpg",
    });
    const importVideo = vi.fn().mockResolvedValue(added);
    const user = userEvent.setup();
    render(
      <VideoWorkspace
        mode="extend"
        runs={client}
        videos={api([clip()], { importVideo })}
        canSave
      />,
    );
    await screen.findByRole("button", { name: /choose: a red fox/i });
    const file = new File(["x"], "holiday_clip.mp4", { type: "video/mp4" });
    await user.upload(screen.getByLabelText("Choose a video file"), file);
    expect(importVideo).toHaveBeenCalledWith(file);
    const card = await screen.findByRole("button", { name: /choose: holiday clip/i });
    expect(card).toHaveAttribute("aria-current", "true"); // chosen at once
    expect(screen.getByRole("textbox")).toHaveValue(""); // the file's name is not what it is about
    await user.type(screen.getByRole("textbox"), "the people keep walking");
    await user.click(make());
    await resultShown();
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body.input).toEqual({
      mode: "extend",
      prompt: "the people keep walking",
      source_id: "v7",
      seconds: 5,
    });
  });

  it("says why a file could not be added and leaves the list as it was", async () => {
    const importVideo = vi
      .fn()
      .mockRejectedValue(new Error("That video is longer than 30 seconds. Try a shorter one."));
    const user = userEvent.setup();
    render(<VideoWorkspace mode="extend" runs={client} videos={api([clip()], { importVideo })} />);
    await screen.findByRole("button", { name: /choose: a red fox/i });
    await user.upload(
      screen.getByLabelText("Choose a video file"),
      new File(["x"], "long.mp4", { type: "video/mp4" }),
    );
    expect(await screen.findByText(/longer than 30 seconds/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /choose: a red fox/i })).toHaveLength(1);
    expect(screen.getByRole("button", { name: /add a video from this computer/i })).toBeEnabled();
  });

  it("offers Extend this on a finished clip, which chooses it here", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), node("generate_video"), ready]));
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockResolvedValueOnce({ videos: [clip()], next_before: null })
      .mockResolvedValue({
        videos: [clip({ id: "v2", prompt: "the fox keeps walking", seconds: 4 }), clip()],
        next_before: null,
      });
    render(<VideoWorkspace mode="extend" runs={client} videos={api([], { list })} />);
    await user.click(await screen.findByRole("button", { name: /choose: a red fox/i }));
    await user.click(make());
    await resultShown();
    await user.click(await screen.findByRole("button", { name: /extend this/i }));
    expect(screen.getByRole("textbox")).toHaveValue("the fox keeps walking");
    expect(screen.getByRole("button", { name: /choose: the fox keeps walking/i })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });
});
