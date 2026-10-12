// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RUN, done, node, sse } from "../test-utils";
import { useImageFlow } from "./use-image-flow";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

const result = done({
  status: "done",
  image_id: "i1",
  image_url: "http://x/i.png",
  thumb_url: "http://x/t.jpg",
  width: 1024,
  height: 1024,
  prompt: "a cat",
  mode: "text",
});

describe("useImageFlow", () => {
  it("runs text to image to the finished picture and forgets the run", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), node("generate_image"), result]));
    const { result: hook } = renderHook(() => useImageFlow());
    act(() => hook.current.start({ mode: "text", prompt: "a cat", size: "wide" }));
    await waitFor(() => expect(hook.current.state.phase).toBe("done"));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/products/wasifyai-image/runs");
    expect(JSON.parse(init.body as string)).toEqual({
      input: { mode: "text", prompt: "a cat", size: "wide" },
    });
    expect(hook.current.state.result?.imageId).toBe("i1");
    expect(sessionStorage.getItem("wasifyai-image:run")).toBeNull();
  });

  it("runs image to image with the key of a picture that is already uploaded", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), result]));
    const { result: hook } = renderHook(() => useImageFlow());
    act(() => hook.current.start({ mode: "image", prompt: "blue", imageKey: "uploads/1.png" }));
    await waitFor(() => expect(hook.current.state.phase).toBe("done"));
    expect(fetchMock).toHaveBeenCalledTimes(1); // no upload here any more (ADR-0039)
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
      input: { mode: "image", prompt: "blue", image_key: "uploads/1.png" },
    });
  });

  it("asks for a picture in picture mode", async () => {
    const { result: hook } = renderHook(() => useImageFlow());
    act(() => hook.current.start({ mode: "image", prompt: "blue" }));
    await waitFor(() => expect(hook.current.state.phase).toBe("error"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("re-attaches to a remembered run after a reload", async () => {
    sessionStorage.setItem("wasifyai-image:run", RUN);
    fetchMock.mockResolvedValueOnce(sse([node("generate_image"), result]));
    const { result: hook } = renderHook(() => useImageFlow());
    await waitFor(() => expect(hook.current.state.phase).toBe("done"));
    expect(fetchMock.mock.calls[0][0]).toContain(`/api/runs/${RUN}/events`);
  });
});
