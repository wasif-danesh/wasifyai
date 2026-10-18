// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type VideoSummary, type VideosApi, createRunClient } from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { done, node, sse } from "../test-utils";
import { VideoLibrary } from "./VideoLibrary";
import { VideoWorkspace } from "./VideoWorkspace";

const fetchMock = vi.fn();
const client = createRunClient({ fetch: (path, init) => fetchMock(path, init) });

beforeEach(() => {
  fetchMock.mockReset();
  sessionStorage.clear();
});

const ready = done({
  status: "done",
  video_id: "v1",
  video_url: "http://127.0.0.1:1/files/v1.mp4",
  poster_url: "http://127.0.0.1:1/files/v1.jpg",
  width: 768,
  height: 512,
  seconds: 2,
  prompt: "a red fox",
  mode: "text",
});

function clip(over: Partial<VideoSummary> = {}): VideoSummary {
  return {
    id: "v1",
    prompt: "A red fox in the snow",
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

function api(over: Partial<VideosApi> = {}): VideosApi {
  return {
    list: vi.fn().mockResolvedValue({ videos: [], next_before: null }),
    search: vi.fn().mockResolvedValue([]),
    get: vi.fn(),
    remove: vi.fn().mockResolvedValue(undefined),
    exportCopy: vi.fn().mockResolvedValue({ name: "a-red-fox.mp4", path: "/Downloads/a.mp4" }),
    ...over,
  };
}

describe("VideoWorkspace", () => {
  it("makes a clip from words: sends the shape and length, shows the player, saves a copy", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), node("generate_video"), ready]));
    const videos = api();
    const user = userEvent.setup();
    const openLibrary = vi.fn();
    render(
      <VideoWorkspace
        mode="text"
        runs={client}
        videos={videos}
        canSave
        onOpenLibrary={openLibrary}
      />,
    );

    await user.type(screen.getByRole("textbox"), "a red fox");
    await user.click(screen.getByRole("button", { name: /5 seconds/i }));
    await user.click(screen.getByRole("button", { name: /portrait/i }));
    await user.click(screen.getByRole("button", { name: /make my video/i }));

    expect(await screen.findByText(/saved in your videos/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/products/wasifyai-video/runs");
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body.input).toEqual({
      mode: "text",
      prompt: "a red fox",
      seconds: 5,
      shape: "portrait",
    });
    const player = document.querySelector("video");
    expect(player).toHaveAttribute("src", "http://127.0.0.1:1/files/v1.mp4");
    expect(player).toHaveAttribute("poster", "http://127.0.0.1:1/files/v1.jpg");

    await user.click(screen.getByRole("button", { name: /save a copy/i }));
    expect(videos.exportCopy).toHaveBeenCalledWith("v1");
    expect(await screen.findByText("Saved as a-red-fox.mp4 in Downloads.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /your videos/i }));
    expect(openLibrary).toHaveBeenCalled();

    // "Make another" brings the form back
    await user.click(screen.getByRole("button", { name: /make another/i }));
    await waitFor(() => expect(screen.getByRole("textbox")).toBeInTheDocument());
  });

  it("needs a picture before it can animate one", async () => {
    render(<VideoWorkspace mode="image" runs={client} />);
    await userEvent.setup().type(screen.getByRole("textbox"), "snow starts to fall");
    expect(screen.getByRole("button", { name: /make my video/i })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /portrait/i })).toBeNull(); // the clip keeps the picture's shape
  });

  it("explains a refusal and keeps what the person wrote", async () => {
    fetchMock.mockResolvedValueOnce(
      sse([
        node("check_request"),
        done({ status: "refused", refusal: { code: "busy", message: "One at a time." } }),
      ]),
    );
    const user = userEvent.setup();
    render(<VideoWorkspace mode="text" runs={client} />);
    await user.type(screen.getByRole("textbox"), "a fox");
    await user.click(screen.getByRole("button", { name: /make my video/i }));
    expect(await screen.findByText("One at a time.")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("a fox");
  });

  it("shows a failure with Try again when the engine cannot be reached", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    const user = userEvent.setup();
    render(<VideoWorkspace mode="text" runs={client} />);
    await user.type(screen.getByRole("textbox"), "a fox");
    await user.click(screen.getByRole("button", { name: /make my video/i }));
    expect(await screen.findByText(/couldn't reach the server/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("shows the notices and refuses to start when the model would not fit", async () => {
    const user = userEvent.setup();
    render(
      <VideoWorkspace
        mode="text"
        runs={client}
        notices={<p>Set up the image engine first.</p>}
        blockedReason="LTX will not fit."
      />,
    );
    expect(screen.getByText("Set up the image engine first.")).toBeInTheDocument();
    expect(screen.getByText("LTX will not fit.")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox"), "a fox");
    await user.click(screen.getByRole("button", { name: /make my video/i }));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("VideoLibrary", () => {
  it("lists clips, opens one in a player, saves a copy and deletes it after asking", async () => {
    const videos = api({
      list: vi.fn().mockResolvedValue({ videos: [clip()], next_before: null }),
    });
    const user = userEvent.setup();
    render(<VideoLibrary videos={videos} canSave />);

    await user.click(await screen.findByRole("button", { name: /open: a red fox/i }));
    expect(document.querySelector("dialog video")).toHaveAttribute(
      "src",
      "http://127.0.0.1:1/files/v1.mp4",
    );
    expect(screen.getByText(/From text · 2 s · 768×512/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /save a copy/i }));
    expect(videos.exportCopy).toHaveBeenCalledWith("v1");

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(videos.remove).not.toHaveBeenCalled(); // asks first
    await user.click(screen.getByRole("button", { name: /yes, delete it/i }));
    expect(videos.remove).toHaveBeenCalledWith("v1");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("No videos yet.")).toBeInTheDocument();
  });

  it("shows a clip being made and a failed one, and looks again while one is being made", async () => {
    // The later polls answer only when the test says so: on a slow runner a 20 ms poll could otherwise
    // finish the clip before the failed one is opened.
    let finish: () => void = () => {};
    const finished = new Promise<void>((resolve) => {
      finish = resolve;
    });
    const list = vi
      .fn()
      .mockResolvedValueOnce({
        videos: [
          clip({ id: "w", status: "working", video_url: null, poster_url: null, prompt: "Busy" }),
          clip({
            id: "f",
            status: "failed",
            error: "It did not work.",
            video_url: null,
            poster_url: null,
            prompt: "Broken",
          }),
        ],
        next_before: null,
      })
      .mockImplementation(async () => {
        await finished;
        return { videos: [clip({ id: "w", prompt: "Busy" })], next_before: null };
      });
    const user = userEvent.setup();
    render(<VideoLibrary videos={api({ list })} pollMs={20} />);

    expect(await screen.findByText("Being made")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /open: broken/i }));
    expect(screen.getByText("It did not work.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));

    // the poll finds it finished
    finish();
    await waitFor(() => expect(screen.queryByText("Being made")).toBeNull());
    expect(list.mock.calls.length).toBeGreaterThan(1);
  });

  it("searches by words and says when nothing matched", async () => {
    const search = vi.fn().mockResolvedValue([]);
    const videos = api({ search });
    const user = userEvent.setup();
    render(<VideoLibrary videos={videos} onCreate={() => {}} />);
    await user.type(await screen.findByRole("searchbox"), "dragon");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(search).toHaveBeenCalledWith("dragon");
    expect(await screen.findByText("Nothing matched “dragon”.")).toBeInTheDocument();
    await act(async () => {});
    await user.click(screen.getByRole("button", { name: /show everything/i }));
    expect(await screen.findByText("No videos yet.")).toBeInTheDocument();
  });
});
