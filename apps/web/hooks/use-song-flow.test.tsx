// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RUN, done, interrupt, node, sse, token } from "../test-utils";
import { useSongFlow } from "./use-song-flow";

const fetchMock = vi.fn();
const KEY = "wasifyai-music:run";

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const lastCall = () => fetchMock.mock.calls.at(-1) as [string, RequestInit];

describe("useSongFlow", () => {
  it("starts a run and lands on the approval step with the draft", async () => {
    fetchMock.mockResolvedValueOnce(
      sse([node("check_request"), node("write_lyrics"), token("[verse]\nla"), interrupt()]),
    );
    const { result } = renderHook(() => useSongFlow());

    act(() => result.current.start({ idea: "rain", genre: "Pop" }));
    expect(result.current.state.phase).toBe("checking"); // instant feedback, before any event

    await waitFor(() => expect(result.current.state.phase).toBe("approving"));
    const [url, init] = lastCall();
    expect(url).toBe("/api/products/wasifyai-music/runs");
    expect(JSON.parse(init.body as string)).toEqual({ input: { idea: "rain", genre: "Pop" } });
    expect(result.current.state.draft?.title).toBe("Rain");
    expect(sessionStorage.getItem(KEY)).toBe(RUN); // so a reload can pick the run up again
  });

  it("answers the approval and follows the run to the finished song", async () => {
    fetchMock.mockResolvedValueOnce(sse([interrupt()]));
    const { result } = renderHook(() => useSongFlow());
    act(() => result.current.start({ idea: "rain" }));
    await waitFor(() => expect(result.current.state.phase).toBe("approving"));

    fetchMock.mockResolvedValueOnce(sse([node("generate_music"), done()], 2));
    act(() => result.current.answer({ action: "approve", title: "New title" }));
    expect(result.current.state.phase).toBe("answering");

    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    const [url, init] = lastCall();
    expect(url).toBe(`/api/runs/${RUN}/resume`);
    expect(JSON.parse(init.body as string)).toEqual({
      value: { action: "approve", title: "New title" },
    });
    expect(result.current.state.result?.songId).toBe("s1");
    expect(sessionStorage.getItem(KEY)).toBeNull(); // finished: nothing to come back to
  });

  it("reconnects from the last event when the stream drops mid-run", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // The connection ends after "making the music", with no terminal event.
    fetchMock.mockResolvedValueOnce(
      sse([node("check_request"), node("write_lyrics"), interrupt(), node("generate_music")]),
    );
    const { result } = renderHook(() => useSongFlow());
    act(() => result.current.start({ idea: "rain" }));
    await waitFor(() => expect(result.current.state.lastSeq).toBe(4));
    expect(result.current.state.phase).toBe("generating");

    fetchMock.mockResolvedValueOnce(sse([done()], 5));
    await act(() => vi.advanceTimersByTimeAsync(1500)); // the backoff before the first retry
    await waitFor(() => expect(result.current.state.phase).toBe("done"));

    const [url, init] = lastCall();
    expect(url).toBe(`/api/runs/${RUN}/events`);
    expect((init.headers as Record<string, string>)["last-event-id"]).toBe("4"); // only what was missed
  });

  it("does not reconnect when the stream legitimately ends at the approval step", async () => {
    fetchMock.mockResolvedValueOnce(sse([interrupt()]));
    const { result } = renderHook(() => useSongFlow());
    act(() => result.current.start({ idea: "rain" }));
    await waitFor(() => expect(result.current.state.phase).toBe("approving"));
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows the server's message when starting fails", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "unknown product" }, { status: 404 }));
    const { result } = renderHook(() => useSongFlow());
    act(() => result.current.start({ idea: "rain" }));
    await waitFor(() => expect(result.current.state.phase).toBe("error"));
    expect(result.current.state.error).toMatchObject({
      message: "unknown product",
      retryable: false,
    });
  });

  it("explains an unreachable server in plain words and lets the user retry", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const { result } = renderHook(() => useSongFlow());
    act(() => result.current.start({ idea: "rain" }));
    await waitFor(() => expect(result.current.state.phase).toBe("error"));
    expect(result.current.state.error?.message).toMatch(/couldn't reach the server/i);
    expect(result.current.state.error?.retryable).toBe(true);

    fetchMock.mockResolvedValueOnce(sse([interrupt()]));
    act(() => result.current.retry()); // re-sends the same idea
    await waitFor(() => expect(result.current.state.phase).toBe("approving"));
    expect(JSON.parse(lastCall()[1].body as string)).toEqual({ input: { idea: "rain" } });
  });

  it("picks a run back up after a reload, replaying it from the start", async () => {
    sessionStorage.setItem(KEY, RUN);
    fetchMock.mockResolvedValueOnce(
      sse([node("check_request"), node("write_lyrics"), token("[verse]\nla"), interrupt()]),
    );
    const { result } = renderHook(() => useSongFlow());

    await waitFor(() => expect(result.current.state.phase).toBe("approving"));
    const [url, init] = lastCall();
    expect(url).toBe(`/api/runs/${RUN}/events`);
    expect((init.headers as Record<string, string>)["last-event-id"]).toBe("0");
    expect(result.current.state.draft?.title).toBe("Rain");
  });

  it("quietly forgets a run that no longer exists", async () => {
    sessionStorage.setItem(KEY, RUN);
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "run not found" }, { status: 404 }));
    const { result } = renderHook(() => useSongFlow());
    await waitFor(() => expect(sessionStorage.getItem(KEY)).toBeNull());
    await waitFor(() => expect(result.current.state.phase).toBe("idle"));
  });

  it("reset cancels the run and clears the stored run", async () => {
    fetchMock.mockResolvedValueOnce(sse([interrupt()]));
    const { result } = renderHook(() => useSongFlow());
    act(() => result.current.start({ idea: "rain" }));
    await waitFor(() => expect(sessionStorage.getItem(KEY)).toBe(RUN));
    act(() => result.current.reset());
    expect(result.current.state.phase).toBe("idle");
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });
});
