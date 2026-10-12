// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POLL_MS, STARTED_EVENT, useVideoActivity } from "./use-video-activity";

const fetchMock = vi.fn();
beforeEach(() => {
  vi.useFakeTimers();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const clip = (id: string, status = "working") => ({
  id,
  status,
  prompt: `clip ${id}`,
  mode: "text",
  seconds: 2,
  created_at: "2026-10-08T00:00:00Z",
  error: status === "failed" ? "It failed." : null,
});
const list = (...videos: object[]) => Response.json({ videos, next_before: null });
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));

describe("useVideoActivity", () => {
  it("asks once, and stays quiet when nothing is being made", async () => {
    fetchMock.mockResolvedValue(list());
    const { result } = renderHook(() => useVideoActivity(true));
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/products/wasifyai-video/videos?status=working&limit=5",
    );
    expect(result.current.working).toEqual([]);
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS * 3)));
    expect(fetchMock).toHaveBeenCalledTimes(1); // no polling while nothing is working
  });

  it("polls while a clip is being made and says when it is ready", async () => {
    fetchMock
      .mockResolvedValueOnce(list(clip("v1")))
      .mockResolvedValueOnce(list(clip("v1")))
      .mockResolvedValueOnce(list()) // it left the working list...
      .mockResolvedValueOnce(Response.json(clip("v1", "done"))); // ...and this is how it ended
    const { result } = renderHook(() => useVideoActivity(true));
    await flush();
    expect(result.current.working.map((v) => v.id)).toEqual(["v1"]);
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS)));
    expect(result.current.notice).toBeNull();
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS)));
    expect(result.current.working).toEqual([]);
    expect(result.current.notice).toEqual({
      id: "v1",
      status: "done",
      prompt: "clip v1",
      error: undefined,
    });
    act(() => result.current.dismiss());
    expect(result.current.notice).toBeNull();
  });

  it("reports a clip that failed with the reason", async () => {
    fetchMock
      .mockResolvedValueOnce(list(clip("v2")))
      .mockResolvedValueOnce(list())
      .mockResolvedValueOnce(Response.json(clip("v2", "failed")));
    const { result } = renderHook(() => useVideoActivity(true));
    await flush();
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS)));
    expect(result.current.notice).toMatchObject({ status: "failed", error: "It failed." });
  });

  it("looks again quickly when the create page starts a clip", async () => {
    fetchMock.mockResolvedValueOnce(list()).mockResolvedValue(list(clip("v3")));
    const { result } = renderHook(() => useVideoActivity(true));
    await flush();
    act(() => void window.dispatchEvent(new Event(STARTED_EVENT)));
    await flush();
    expect(result.current.working.map((v) => v.id)).toEqual(["v3"]);
  });

  it("does nothing when signed out, and stops when the API says so", async () => {
    renderHook(() => useVideoActivity(false));
    await flush();
    expect(fetchMock).not.toHaveBeenCalled();
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 401 }));
    const { result } = renderHook(() => useVideoActivity(true));
    await flush();
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS * 3)));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.working).toEqual([]);
  });
});
