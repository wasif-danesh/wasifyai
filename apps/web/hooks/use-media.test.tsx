// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mediaProblem, useMedia } from "./use-media";

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

const file = (type = "audio/mpeg", size = 2000, name = "talk.mp3") =>
  new File([new Uint8Array(size)], name, { type });
const uploaded = (key = "uploads/a.wav") =>
  Response.json({ upload_id: "u1", key, seconds: 12.3, bytes: 99 }, { status: 201 });

describe("mediaProblem", () => {
  it("accepts audio and video, and says why not otherwise", () => {
    expect(mediaProblem(file("audio/mpeg"), 10_000)).toBeNull();
    expect(mediaProblem(file("video/mp4"), 10_000)).toBeNull();
    expect(mediaProblem(file(""), 10_000)).toBeNull(); // the server decides by the first bytes
    expect(mediaProblem(file("image/png"), 10_000)).toMatch(/audio or video/);
    expect(mediaProblem(file("audio/mpeg", 0), 10_000)).toMatch(/empty/);
    expect(mediaProblem(file("audio/mpeg", 3 * 1024 * 1024), 1024 * 1024)).toMatch(/over 1 MB/);
  });
});

describe("useMedia", () => {
  it("uploads a chosen file at once and keeps its key and length", async () => {
    fetchMock.mockResolvedValue(uploaded());
    const { result } = renderHook(() => useMedia("wasifyai-stt", 100_000));
    await act(async () => result.current.choose(file()));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/products/wasifyai-stt/uploads/media");
    expect(result.current.recording).toMatchObject({
      key: "uploads/a.wav",
      seconds: 12.3,
      name: "talk.mp3",
    });
    expect(result.current.status).toBe("idle");
  });

  it("does not upload a file that cannot be used", async () => {
    const { result } = renderHook(() => useMedia("wasifyai-stt", 1000));
    await act(async () => result.current.choose(file("audio/mpeg", 5000)));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/over/);
    expect(result.current.status).toBe("error");
  });

  it("shows the server's reason when it refuses a file", async () => {
    fetchMock.mockResolvedValue(
      Response.json({ detail: "That file could not be read as audio." }, { status: 422 }),
    );
    const { result } = renderHook(() => useMedia("wasifyai-stt", 100_000));
    await act(async () => result.current.choose(file()));
    expect(result.current.error).toBe("That file could not be read as audio.");
    expect(result.current.recording).toBeNull();
  });

  it("takes the recording back from the server when it is removed", async () => {
    fetchMock
      .mockResolvedValueOnce(uploaded())
      .mockResolvedValue(new Response(null, { status: 204 }));
    const { result } = renderHook(() => useMedia("wasifyai-stt", 100_000));
    await act(async () => result.current.choose(file()));
    act(() => result.current.clear());
    expect(fetchMock.mock.calls[1][0]).toBe("/api/products/wasifyai-stt/uploads/media/u1");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "DELETE" });
    expect(result.current.recording).toBeNull();
  });

  it("leaves the recording alone once a run owns it", async () => {
    fetchMock.mockResolvedValue(uploaded());
    const { result, unmount } = renderHook(() => useMedia("wasifyai-stt", 100_000));
    await act(async () => result.current.choose(file()));
    act(() => result.current.handOver());
    unmount();
    expect(fetchMock).toHaveBeenCalledTimes(1); // no delete
  });
});
