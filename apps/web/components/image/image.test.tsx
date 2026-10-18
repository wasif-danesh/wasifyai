import { putHandoff, takeHandoff } from "@/lib/handoff";
// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ImageSummary } from "@wasifyai/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ImageLibraryScreen, ImageScreen } from "./ImageScreens";
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
  recipe: null,
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

function routes(extra: Record<string, () => Response> = {}) {
  const answers: Record<string, () => Response> = {
    "/api/products/wasifyai-image/images?limit=14": () =>
      Response.json({ images: [], next_before: null }),
    ...extra,
  };
  fetchMock.mockImplementation(async (path: string) => {
    const key = Object.keys(answers).find((k) => path.startsWith(k));
    if (!key) throw new Error(`unexpected ${path}`);
    return answers[key]?.();
  });
}

const ready = {
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

describe("ImageScreen (the web app's mount of the shared screen)", () => {
  it("goes through the BFF, and offers the download and the library", async () => {
    const user = userEvent.setup();
    routes({
      "/api/products/wasifyai-image/runs": () =>
        new Response(`id: 2\nevent: done\ndata: ${JSON.stringify(ready)}\n\n`, {
          headers: { "content-type": "text/event-stream" },
        }),
      "/api/products/wasifyai-image/images/i9": () => Response.json(img("i9", "a lighthouse")),
    });
    render(<ImageScreen mode="text" />);
    await user.type(await screen.findByRole("textbox"), "a lighthouse");
    await user.click(screen.getByRole("button", { name: /generate/i }));

    expect(await screen.findByRole("img", { name: "a lighthouse" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-image/images/i9/download",
    );
    await user.click(screen.getByRole("button", { name: /library/i }));
    expect(push).toHaveBeenCalledWith("/image/library");
  });

  it("starts from a recipe sent from the library, once", async () => {
    putHandoff("image-again", { prompt: "a teapot", size: "square", seed: 7, loras: [] });
    routes();
    const { unmount } = render(<ImageScreen mode="text" />);
    expect(await screen.findByDisplayValue("a teapot")).toBeInTheDocument();
    unmount();
    render(<ImageScreen mode="text" />);
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(""));
  });
});

describe("ImageLibraryScreen", () => {
  it("lists images with a download, and sends a recipe to Create to make it again", async () => {
    const user = userEvent.setup();
    const made = {
      ...img("i1", "a lighthouse"),
      recipe: {
        v: 1,
        mode: "text",
        prompt: "a lighthouse",
        size: "square",
        width: 1024,
        height: 1024,
        seed: 5,
      },
    };
    routes({
      "/api/products/wasifyai-image/images?limit=36": () =>
        Response.json({ images: [made], next_before: null }),
    });
    render(<ImageLibraryScreen />);
    await user.click(await screen.findByRole("button", { name: /open: a lighthouse/i }));
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-image/images/i1/download",
    );
    await user.click(screen.getByRole("button", { name: /make it again/i }));
    expect(push).toHaveBeenCalledWith("/image");
    expect(takeHandoff<{ seed: number }>("image-again")?.seed).toBe(5);
  });
});
