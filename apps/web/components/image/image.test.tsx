// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ImageSummary } from "@wasifyai/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CreateImage } from "./CreateImage";
import { ImageView } from "./ImageView";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  usePathname: () => "/image",
}));

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  push.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

const img = (id: string, prompt = "a cat"): ImageSummary => ({
  id,
  prompt,
  mode: "text",
  width: 1024,
  height: 1024,
  created_at: "2026-10-08T00:00:00Z",
  image_url: `http://x/${id}.png`,
  thumb_url: `http://x/${id}.jpg`,
  favourite: false,
});

describe("ImageView", () => {
  it("asks twice before deleting, then returns to the list", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<ImageView image={img("a")} when="today" />);
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-image/images/a/download",
    );
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /yes, delete/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/creations"));
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "DELETE" });
  });

  it("can be cancelled and reports a failure", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 500 }));
    render(<ImageView image={img("a")} when="today" />);
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /keep it/i }));
    expect(screen.getByRole("button", { name: /^delete$/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /yes, delete/i }));
    await waitFor(() => expect(screen.getByText(/couldn't delete/i)).toBeInTheDocument());
    expect(push).not.toHaveBeenCalled();
  });
});

describe("CreateImage (the web app's mount of the shared screen)", () => {
  it("goes through the BFF, and links the download and My creations", async () => {
    const user = userEvent.setup();
    const done = {
      run_id: "r1",
      thread_id: "t1",
      seq: 2,
      ts: "",
      outputs: {
        status: "done",
        image_id: "i9",
        image_url: "http://x/i9.png",
        thumb_url: "http://x/i9.jpg",
        width: 1024,
        height: 1024,
        prompt: "a lighthouse",
        mode: "text",
      },
    };
    fetchMock.mockResolvedValueOnce(
      new Response(`id: 2\nevent: done\ndata: ${JSON.stringify(done)}\n\n`, {
        headers: { "content-type": "text/event-stream" },
      }),
    );
    render(<CreateImage />);
    await user.type(screen.getByRole("textbox"), "a lighthouse");
    await user.click(screen.getByRole("button", { name: /make my image/i }));

    expect(await screen.findByRole("img", { name: "a lighthouse" })).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/products/wasifyai-image/runs");
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-image/images/i9/download",
    );
    expect(screen.getByRole("link", { name: /open in my creations/i })).toHaveAttribute(
      "href",
      "/image/creations/i9",
    );
  });
});
