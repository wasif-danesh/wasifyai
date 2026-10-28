// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type VideoSummary, type VideosApi, createRunClient } from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SaveAsProvider } from "../save";
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
    importVideo: vi.fn(),
    ...over,
  };
}

describe("VideoWorkspace", () => {
  it("makes a clip from words: sends the shape and length, plays it on the stage, saves a copy", async () => {
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
    expect(screen.getByText("Your video appears here.")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox"), "a red fox");
    await user.click(screen.getByRole("button", { name: /8 seconds/i }));
    await user.click(screen.getByRole("button", { name: /portrait/i }));
    await user.click(screen.getByRole("button", { name: "Make the video" }));

    const stage = await screen.findByRole("region", { name: "Result" });
    await waitFor(() => expect(stage).toHaveAttribute("data-state", "result"));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/products/wasifyai-video/runs");
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body.input).toEqual({
      mode: "text",
      prompt: "a red fox",
      seconds: 8,
      shape: "portrait",
    });
    const player = stage.querySelector("video");
    expect(player).toHaveAttribute("src", "http://127.0.0.1:1/files/v1.mp4");
    expect(player).toHaveAttribute("poster", "http://127.0.0.1:1/files/v1.jpg");
    expect(screen.getByText(/kept in your videos/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /save a copy/i }));
    expect(videos.exportCopy).toHaveBeenCalledWith("v1", undefined);
    expect(await screen.findByText("Saved as a-red-fox.mp4 in Downloads.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "See all" }));
    expect(openLibrary).toHaveBeenCalled();
    // the words stay in the box for the next clip
    expect(screen.getByRole("textbox")).toHaveValue("a red fox");
  });

  it("lists the recent clips, plays one on the stage, and hands it to Extend", async () => {
    const videos = api({
      list: vi.fn().mockResolvedValue({ videos: [clip()], next_before: null }),
    });
    const extend = vi.fn();
    const user = userEvent.setup();
    render(<VideoWorkspace mode="text" runs={client} videos={videos} onExtendThis={extend} />);
    expect(videos.list).toHaveBeenCalledWith(expect.objectContaining({ status: "done" }));
    await user.click(await screen.findByRole("button", { name: /open: a red fox/i }));
    expect(screen.getByRole("region", { name: "Result" }).querySelector("video")).toHaveAttribute(
      "src",
      "http://127.0.0.1:1/files/v1.mp4",
    );
    await user.click(screen.getByRole("button", { name: /extend this/i }));
    expect(extend).toHaveBeenCalledWith(expect.objectContaining({ id: "v1" }));
  });

  it("animates a picture sent from Images: fetches it and uploads it like one the person chose", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          upload_id: "u1",
          key: "uploads/u1.png",
          width: 512,
          height: 512,
          bytes: 1,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const realFetch = globalThis.fetch;
    // jsdom's Blob does not survive a Response, so the fetched picture is a stand-in with blob()
    globalThis.fetch = vi.fn(async () => ({
      blob: async () => new Blob(["x"], { type: "image/png" }),
    })) as unknown as typeof fetch;
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
    try {
      render(
        <VideoWorkspace
          mode="image"
          runs={client}
          sourceImage={{ url: "http://127.0.0.1:1/files/i1.png", name: "i1.png" }}
        />,
      );
      await waitFor(() =>
        expect(fetchMock.mock.calls[0]?.[0]).toBe("/products/wasifyai-video/uploads/images"),
      );
      expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:1/files/i1.png");
      expect((fetchMock.mock.calls[0]?.[1]?.body as File).name).toBe("i1.png");
    } finally {
      globalThis.fetch = realFetch;
    }
  });

  it("shows My looks only when there are any, and sends the chosen look with its strength and magic word", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), node("generate_video"), ready]));
    const user = userEvent.setup();
    const looks = [
      { name: "wasify-video-ena-12345678.safetensors", title: "Ena", word: "enaz" },
      { name: "wasify-video-fog-87654321.safetensors", title: "Fog", word: "fogzy" },
    ];
    const { unmount } = render(<VideoWorkspace mode="text" runs={client} />);
    expect(screen.queryByRole("region", { name: "My looks" })).toBeNull();
    unmount();

    render(<VideoWorkspace mode="text" runs={client} looks={looks} />);
    await user.click(screen.getByRole("button", { name: /My looks/ }));
    await user.click(screen.getByRole("checkbox", { name: /Ena/ }));
    const slider = screen.getByRole("slider", { name: "Strength of Ena" });
    expect((slider as HTMLInputElement).value).toBe("1.5");
    fireEvent.change(slider, { target: { value: "2" } });
    await user.type(screen.getByRole("textbox"), "walking in snow");
    await user.click(screen.getByRole("button", { name: "Make the video" }));
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Result" })).toHaveAttribute(
        "data-state",
        "result",
      ),
    );
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body.input.prompt).toBe("enaz, walking in snow");
    expect(body.input.loras).toEqual([
      { name: "wasify-video-ena-12345678.safetensors", weight: 2 },
    ]);
  });

  it("allows two looks at most", async () => {
    const user = userEvent.setup();
    const looks = ["a", "b", "c"].map((n) => ({
      name: `${n}.safetensors`,
      title: n,
      word: `${n}word`,
    }));
    render(<VideoWorkspace mode="text" runs={client} looks={looks} />);
    await user.click(screen.getByRole("button", { name: /My looks/ }));
    await user.click(screen.getByRole("checkbox", { name: /^a/ }));
    await user.click(screen.getByRole("checkbox", { name: /^b/ }));
    expect((screen.getByRole("checkbox", { name: /^c/ }) as HTMLInputElement).disabled).toBe(true);
  });

  it("needs a picture before it can animate one", async () => {
    render(<VideoWorkspace mode="image" runs={client} />);
    await userEvent.setup().type(screen.getByRole("textbox"), "snow starts to fall");
    expect(screen.getByRole("button", { name: "Make the video" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /portrait/i })).toBeNull(); // the clip keeps the picture's shape
  });

  it("explains a refusal on the stage and keeps what the person wrote", async () => {
    fetchMock.mockResolvedValueOnce(
      sse([
        node("check_request"),
        done({ status: "refused", refusal: { code: "busy", message: "One at a time." } }),
      ]),
    );
    const user = userEvent.setup();
    render(<VideoWorkspace mode="text" runs={client} />);
    await user.type(screen.getByRole("textbox"), "a fox");
    await user.click(screen.getByRole("button", { name: "Make the video" }));
    expect(await screen.findByText("One at a time.")).toBeInTheDocument();
    expect(screen.getByText("We can't make that one")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("a fox");
  });

  it("shows a failure with Try again when the engine cannot be reached", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    const user = userEvent.setup();
    render(<VideoWorkspace mode="text" runs={client} />);
    await user.type(screen.getByRole("textbox"), "a fox");
    await user.click(screen.getByRole("button", { name: "Make the video" }));
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
    expect(screen.getByRole("button", { name: "Make the video" })).toBeDisabled();
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
    expect(videos.exportCopy).toHaveBeenCalledWith("v1", undefined);
    expect(screen.queryByRole("button", { name: /extend this/i })).toBeNull(); // only when the app offers it

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(videos.remove).not.toHaveBeenCalled(); // asks first
    await user.click(screen.getByRole("button", { name: /yes, delete it/i }));
    expect(videos.remove).toHaveBeenCalledWith("v1");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("No videos yet.")).toBeInTheDocument();
  });

  it("in the app window asks where to save the clip, with a name from its words, and writes it there", async () => {
    const videos = api({
      list: vi.fn().mockResolvedValue({ videos: [clip()], next_before: null }),
      exportCopy: vi.fn(async (_id: string, path?: string) => ({
        name: "fox.mp4",
        path: path ?? "",
      })),
    });
    const choose = vi.fn<(name: string) => Promise<string | null>>(
      async () => "/Users/me/Movies/fox.mp4",
    );
    const user = userEvent.setup();
    render(
      <SaveAsProvider value={{ choose, write: vi.fn() }}>
        <VideoLibrary videos={videos} canSave />
      </SaveAsProvider>,
    );
    await user.click(await screen.findByRole("button", { name: /open: a red fox/i }));
    await user.click(screen.getByRole("button", { name: /save a copy/i }));
    expect(choose).toHaveBeenCalledWith("a-red-fox-in-the-snow.mp4");
    expect(videos.exportCopy).toHaveBeenCalledWith("v1", "/Users/me/Movies/fox.mp4");
    expect((await screen.findAllByText("Saved as fox.mp4 in Movies.")).length).toBeGreaterThan(0);
    choose.mockResolvedValueOnce(null); // cancelled: nothing more is saved
    await user.click(screen.getByRole("button", { name: /save a copy/i }));
    await new Promise((r) => setTimeout(r, 20));
    expect(videos.exportCopy).toHaveBeenCalledTimes(1);
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
