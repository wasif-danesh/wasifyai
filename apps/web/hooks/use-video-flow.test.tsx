// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RUN, done, node, sse } from "../test-utils";
import { useVideoFlow } from "./use-video-flow";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

const finished = done({
  status: "done",
  video_id: "v1",
  video_url: "http://x/v.mp4",
  poster_url: "http://x/p.jpg",
  width: 768,
  height: 512,
  seconds: 2,
  prompt: "a fox",
  mode: "text",
});

describe("useVideoFlow", () => {
  it("starts a text clip with its shape and length and reaches 'being made'", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), node("generate_video")]));
    const { result } = renderHook(() => useVideoFlow());
    act(() =>
      result.current.start({ mode: "text", prompt: "a fox", shape: "portrait", seconds: 5 }),
    );
    expect(result.current.state.phase).toBe("checking");
    await waitFor(() => expect(result.current.state.phase).toBe("making"));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/products/wasifyai-video/runs");
    expect(JSON.parse(init.body as string)).toEqual({
      input: { mode: "text", prompt: "a fox", seconds: 5, shape: "portrait" },
    });
    expect(sessionStorage.getItem("wasifyai-video:run")).toBe(RUN); // a reload can pick it up
  });

  it("runs image to video with the key of a picture that is already uploaded", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), finished]));
    const { result } = renderHook(() => useVideoFlow());
    act(() =>
      result.current.start({
        mode: "image",
        prompt: "snow",
        seconds: 2,
        imageKey: "uploads/1.png",
      }),
    );
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
      input: { mode: "image", prompt: "snow", seconds: 2, image_key: "uploads/1.png" },
    });
    expect(result.current.state.result?.videoId).toBe("v1");
    expect(sessionStorage.getItem("wasifyai-video:run")).toBeNull(); // finished: nothing to restore
  });

  it("asks for a picture in picture mode", async () => {
    const { result } = renderHook(() => useVideoFlow());
    act(() => result.current.start({ mode: "image", prompt: "snow", seconds: 2 }));
    await waitFor(() => expect(result.current.state.phase).toBe("error"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("re-attaches to a remembered run after a reload", async () => {
    sessionStorage.setItem("wasifyai-video:run", RUN);
    fetchMock.mockResolvedValueOnce(sse([node("generate_video"), finished]));
    const { result } = renderHook(() => useVideoFlow());
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    expect(fetchMock.mock.calls[0][0]).toContain(`/api/runs/${RUN}/events`);
  });
});
