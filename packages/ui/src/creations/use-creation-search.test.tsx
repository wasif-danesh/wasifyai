// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { createCreationsApi } from "@wasifyai/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEBOUNCE_MS, useCreationSearch as useSearch } from "./use-creation-search";

const fetchMock = vi.fn();
const api = createCreationsApi({ fetch: (path, init) => fetchMock(path, init) });
const useCreationSearch = (query: string, filter: Parameters<typeof useSearch>[2]) =>
  useSearch(api, query, filter);
beforeEach(() => {
  vi.useFakeTimers();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const hit = (kind: string, id: string, match = "meaning") => ({
  kind,
  product_id: `wasifyai-${kind}-ai`,
  id,
  score: 0.7,
  match,
});
const song = (id: string) => ({
  id,
  title: `Song ${id}`,
  style: "pop",
  created_at: "2026-10-08T00:00:00Z",
  audio_url: "a",
});
const image = (id: string) => ({
  id,
  prompt: `Image ${id}`,
  mode: "text",
  width: 1,
  height: 1,
  created_at: "2026-10-08T01:00:00Z",
  image_url: "i",
  thumb_url: "t",
});
const settle = () => act(async () => void (await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 10)));

describe("useCreationSearch and the voice product", () => {
  it("finds a speech the voice product keeps, even when the older speech product is gone", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path.includes("/creations/search")) {
        return Response.json({ query: "hello", degraded: false, results: [hit("speech", "v1")] });
      }
      if (path.startsWith("/products/wasifyai-voice/speeches")) {
        return Response.json({
          items: [
            {
              id: "v1",
              text: "Hello there",
              voice: "alloy",
              seconds: 2,
              created_at: "2026-10-18T00:00:00Z",
              audio_url: "a",
            },
          ],
        });
      }
      return Response.json({ detail: "no such product" }, { status: 404 });
    });
    const { result } = renderHook(() => useCreationSearch("hello", "all"));
    await settle();
    expect(result.current.status).toBe("done");
    if (result.current.status !== "done") return;
    expect(result.current.entries.map((e) => `${e.kind}:${e.id}`)).toEqual(["speech:v1"]);
  });
});

describe("useCreationSearch", () => {
  it("is not a search below two characters", async () => {
    const { result } = renderHook(() => useCreationSearch(" a ", "all"));
    await settle();
    expect(result.current.status).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("lets one Chinese, Japanese or Korean character through, because it can be a whole word", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ query: "龙", degraded: false, results: [] }));
    const { result } = renderHook(() => useCreationSearch("龙", "all"));
    await settle();
    expect(result.current.status).toBe("done");
    expect(fetchMock.mock.calls[0][0]).toContain("q=%E9%BE%99");
  });

  it("waits for the user to stop typing, asks once, and puts the cards in the order search ranked", async () => {
    fetchMock
      .mockResolvedValueOnce(
        Response.json({
          query: "rain madrid",
          degraded: false,
          results: [hit("image", "i1"), hit("track", "s2", "words"), hit("track", "s1")],
        }),
      )
      .mockResolvedValueOnce(Response.json({ images: [image("i1")], next_before: null }))
      .mockResolvedValueOnce(Response.json({ items: [song("s1"), song("s2")] }));
    const { result, rerender } = renderHook(({ q }) => useCreationSearch(q, "all"), {
      initialProps: { q: "ra" },
    });
    rerender({ q: "rain" });
    rerender({ q: "rain  madrid " });
    expect(result.current.status).toBe("searching");
    expect(fetchMock).not.toHaveBeenCalled(); // still typing
    await settle();
    const urls = fetchMock.mock.calls.map((c) => c[0] as string);
    expect(urls[0]).toBe("/creations/search?q=rain+madrid&limit=30");
    expect(urls.slice(1).sort()).toEqual([
      "/products/wasifyai-image/images?ids=i1",
      "/products/wasifyai-voice/tracks?ids=s2,s1",
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const s = result.current;
    if (s.status !== "done") throw new Error(`expected done, got ${s.status}`);
    expect(s.entries.map((e) => `${e.kind}:${e.id}`)).toEqual(["image:i1", "song:s2", "song:s1"]);
    expect([...s.words]).toEqual(["s2"]);
    expect(s.degraded).toBe(false);
  });

  it("sends the filter as a kind and skips results whose card has gone", async () => {
    fetchMock
      .mockResolvedValueOnce(
        Response.json({
          query: "fox",
          degraded: true,
          results: [hit("image", "gone"), hit("image", "i1")],
        }),
      )
      .mockResolvedValueOnce(Response.json({ images: [image("i1")], next_before: null }));
    const { result } = renderHook(() => useCreationSearch("fox", "images"));
    await settle();
    expect(fetchMock.mock.calls[0][0]).toBe("/creations/search?q=fox&limit=30&kind=image");
    const s = result.current;
    if (s.status !== "done") throw new Error("expected done");
    expect(s.entries.map((e) => e.id)).toEqual(["i1"]);
    expect(s.degraded).toBe(true);
  });

  it("explains a rate limit and a server problem in plain words", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 429 }));
    const { result, rerender } = renderHook(({ q }) => useCreationSearch(q, "all"), {
      initialProps: { q: "fox" },
    });
    await settle();
    expect(result.current).toMatchObject({
      status: "error",
      message: expect.stringMatching(/searched a lot/),
    });
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    rerender({ q: "fox snow" });
    await settle();
    expect(result.current).toMatchObject({
      status: "error",
      message: expect.stringMatching(/reach the server/),
    });
  });

  it("drops an answer that arrives after the user has typed something else", async () => {
    let release: (r: Response) => void = () => {};
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    fetchMock.mockResolvedValueOnce(
      Response.json({ query: "second", degraded: false, results: [] }),
    );
    const { result, rerender } = renderHook(({ q }) => useCreationSearch(q, "all"), {
      initialProps: { q: "first" },
    });
    await settle();
    rerender({ q: "second" });
    await settle();
    await act(async () =>
      release(Response.json({ query: "first", degraded: false, results: [hit("track", "late")] })),
    );
    const s = result.current;
    if (s.status !== "done") throw new Error("expected done");
    expect(s.query).toBe("second");
    expect(s.entries).toEqual([]);
  });
});
