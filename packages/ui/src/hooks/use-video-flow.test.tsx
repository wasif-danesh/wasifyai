// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { createRunClient } from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { done, node, sse } from "../test-utils";
import { useVideoFlow } from "./use-video-flow";

const fetchMock = vi.fn();
const client = createRunClient({ fetch: (path, init) => fetchMock(path, init) });
beforeEach(() => {
  fetchMock.mockReset();
  sessionStorage.clear();
});

describe("useVideoFlow", () => {
  it("sends the model the person chose (ADR-0097)", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), done({ status: "done" })]));
    const { result: hook } = renderHook(() => useVideoFlow(client));
    act(() =>
      hook.current.start({
        mode: "text",
        prompt: "a fox",
        shape: "landscape",
        seconds: 5,
        model: "wan2.2-14b",
      }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/products/wasifyai-video/runs");
    expect(JSON.parse(init.body as string).input).toEqual({
      mode: "text",
      prompt: "a fox",
      seconds: 5,
      shape: "landscape",
      model: "wan2.2-14b",
    });
  });
});
