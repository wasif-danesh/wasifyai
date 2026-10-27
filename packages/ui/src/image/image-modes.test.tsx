// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type ImageSummary, type ImagesApi, createRunClient } from "@wasifyai/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { done, node, sse } from "../test-utils";
import { ImageWorkspace } from "./ImageWorkspace";

const fetchMock = vi.fn();
const runs = createRunClient({ fetch: (path, init) => fetchMock(path, init) });
const png = (name = "a.png") => new File(["x"], name, { type: "image/png" });

const api: ImagesApi = {
  async list() {
    return { images: [], next_before: null };
  },
  async search() {
    return [];
  },
  async get() {
    throw new Error("missing");
  },
  async remove() {},
  async setFavourite() {
    throw new Error("unused");
  },
  async exportCopy() {
    return { name: "x.png", path: "/x.png" };
  },
} satisfies ImagesApi;

const upload = (n: number) =>
  Response.json({
    upload_id: `u${n}`,
    key: `uploads/u${n}.png`,
    width: 200,
    height: 100,
    bytes: 9,
  });

const made = (mode: string) =>
  sse([
    node("check_request"),
    done({
      status: "done",
      image_id: "new",
      image_url: "http://127.0.0.1:1/files/new.png",
      thumb_url: "http://127.0.0.1:1/files/new.jpg",
      width: 1024,
      height: 1024,
      prompt: "x",
      mode,
    }),
  ]);

/** The run the screen started: its path and the body it sent. */
function startedRun() {
  const call = fetchMock.mock.calls.find((c) => c[0] === "/products/wasifyai-image/runs");
  return call ? JSON.parse(call[1].body as string).input : null;
}

// jsdom has no canvas: a small one that remembers which pixels are painted, so the painter's own logic runs
const SIDE = { w: 200, h: 100 };
let pixels: Uint8ClampedArray;
let exported: Blob | null = null;
function fakeContext() {
  const w = SIDE.w;
  const h = SIDE.h;
  let erasing = false;
  let keepOnly = false;
  let width = 1;
  const fill = (x: number, y: number, rw: number, rh: number, alpha: number) => {
    for (let j = Math.max(0, Math.floor(y)); j < Math.min(h, Math.ceil(y + rh)); j++)
      for (let i = Math.max(0, Math.floor(x)); i < Math.min(w, Math.ceil(x + rw)); i++)
        pixels[(j * w + i) * 4 + 3] = alpha;
  };
  let last = { x: 0, y: 0 };
  return {
    fillStyle: "",
    strokeStyle: "",
    lineCap: "",
    lineJoin: "",
    set lineWidth(v: number) {
      width = v;
    },
    set globalCompositeOperation(v: string) {
      erasing = v === "destination-out";
      keepOnly = v === "source-in";
    },
    save() {},
    restore() {},
    beginPath() {},
    moveTo(x: number, y: number) {
      last = { x, y };
    },
    lineTo(x: number, y: number) {
      fill(x - width / 2, y - width / 2, width, width, erasing ? 0 : 255);
    },
    stroke() {},
    clearRect() {
      pixels.fill(0);
    },
    fillRect(x: number, y: number, rw: number, rh: number) {
      if (keepOnly) return; // "source-in" colours what is there and adds nothing: alpha stays as it is
      fill(x, y, rw, rh, 255);
    },
    getImageData() {
      return { data: new Uint8ClampedArray(pixels), width: w, height: h };
    },
    putImageData(d: { data: Uint8ClampedArray }) {
      pixels.set(d.data);
    },
    get _last() {
      return last;
    },
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  sessionStorage.clear();
  pixels = new Uint8ClampedArray(SIDE.w * SIDE.h * 4);
  exported = null;
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} }),
  );
  HTMLCanvasElement.prototype.getContext = vi.fn(() => fakeContext()) as never;
  HTMLCanvasElement.prototype.toBlob = vi.fn((cb: (b: Blob | null) => void) => {
    exported = new Blob(["png"], { type: "image/png" });
    cb(exported);
  }) as never;
  HTMLElement.prototype.setPointerCapture = vi.fn();
  HTMLCanvasElement.prototype.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: SIDE.w, height: SIDE.h, right: SIDE.w, bottom: SIDE.h }) as DOMRect;
});
afterEach(() => vi.unstubAllGlobals());

describe("Reference", () => {
  it("needs both pictures and a prompt, then sends both with the size", async () => {
    fetchMock.mockResolvedValueOnce(upload(1)).mockResolvedValueOnce(upload(2));
    fetchMock.mockResolvedValueOnce(made("reference"));
    const user = userEvent.setup({ applyAccept: false });
    render(<ImageWorkspace mode="reference" runs={runs} images={api} />);
    expect(
      screen.getByRole("heading", { name: "Make a picture from two pictures" }),
    ).toBeInTheDocument();
    const generate = screen.getByRole("button", { name: "Make the picture" });
    await user.type(
      screen.getByRole("textbox"),
      "the cat from picture 1 on the chair from picture 2",
    );
    expect(generate).toBeDisabled(); // no pictures yet

    await user.upload(screen.getByLabelText("Picture 1"), png("cat.png"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(generate).toBeDisabled(); // one is not enough
    await user.upload(screen.getByLabelText("Picture 2"), png("chair.png"));
    await waitFor(() => expect(generate).toBeEnabled());

    await user.click(screen.getByRole("button", { name: /wide/i })); // the size is the person's choice
    await user.click(generate);
    await waitFor(() => expect(startedRun()).not.toBeNull());
    expect(startedRun()).toMatchObject({
      mode: "reference",
      prompt: "the cat from picture 1 on the chair from picture 2",
      size: "wide",
      image_key: "uploads/u1.png",
      image2_key: "uploads/u2.png",
    });
    expect(startedRun()).not.toHaveProperty("mask_key");
    expect(await screen.findByRole("button", { name: /Recipe/ })).toBeInTheDocument();
  });

  it("has no Enhance button and says how to name the pictures", () => {
    render(<ImageWorkspace mode="reference" runs={runs} images={api} />);
    expect(screen.queryByRole("button", { name: /enhance/i })).toBeNull();
    expect(screen.getByText(/Call them “picture 1” and “picture 2”/)).toBeInTheDocument();
  });
});

describe("Inpaint", () => {
  async function withPicture(user: ReturnType<typeof userEvent.setup>) {
    fetchMock.mockResolvedValueOnce(upload(1));
    render(<ImageWorkspace mode="inpaint" runs={runs} images={api} />);
    expect(screen.queryByRole("img", { name: /painted area/i })).toBeNull(); // nothing to paint on yet
    await user.upload(screen.getByLabelText("Your picture"), png("plant.png"));
    return screen.findByRole("img", { name: /painted area/i });
  }

  const paintRectangle = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByText("Choose a rectangle by numbers"));
    await user.click(screen.getByRole("button", { name: "Paint this rectangle" }));
  };

  it("shows the painter once a picture is chosen, and Generate waits for something painted", async () => {
    const user = userEvent.setup({ applyAccept: false });
    await withPicture(user);
    await user.type(screen.getByRole("textbox"), "a white cup");
    const generate = screen.getByRole("button", { name: "Make the picture" });
    expect(generate).toBeDisabled();
    expect(screen.getByText("Nothing painted yet.")).toBeInTheDocument();

    await paintRectangle(user); // 30 % x 30 % of the picture
    expect(await screen.findByText("9% of the picture is painted.")).toBeInTheDocument();
    expect(generate).toBeEnabled();
  });

  it("paints with the brush and takes it back with the eraser, undo and clear", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const canvas = await withPicture(user);
    fireEvent.pointerDown(canvas, { clientX: 100, clientY: 50, pointerId: 1 });
    fireEvent.pointerMove(canvas, { clientX: 110, clientY: 50, pointerId: 1 });
    fireEvent.pointerUp(canvas, { pointerId: 1 });
    expect(screen.queryByText("Nothing painted yet.")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Eraser" }));
    expect(screen.getByRole("button", { name: "Eraser" })).toHaveAttribute("aria-pressed", "true");
    for (const x of [100, 110]) {
      fireEvent.pointerDown(canvas, { clientX: x, clientY: 50, pointerId: 1 });
      fireEvent.pointerUp(canvas, { pointerId: 1 });
    }
    // the eraser dabs are smaller than the brush stroke, so some paint can remain; clear removes it all
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(await screen.findByText("Nothing painted yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" })); // the clear is undone
    expect(screen.queryByText("Nothing painted yet.")).toBeNull();
  });

  it("inverts what is painted", async () => {
    const user = userEvent.setup({ applyAccept: false });
    await withPicture(user);
    await paintRectangle(user);
    await screen.findByText("9% of the picture is painted.");
    await user.click(screen.getByRole("button", { name: "Invert" }));
    expect(await screen.findByText("91% of the picture is painted.")).toBeInTheDocument();
  });

  it("sends the painted area as a picture of its own, and the keys to the run", async () => {
    const user = userEvent.setup({ applyAccept: false });
    await withPicture(user);
    fetchMock.mockResolvedValueOnce(upload(2)); // the mask goes up when Generate is pressed
    fetchMock.mockResolvedValueOnce(made("inpaint"));
    await user.type(screen.getByRole("textbox"), "a white cup");
    await paintRectangle(user);
    await user.click(await screen.findByRole("button", { name: "Make the picture" }));
    await waitFor(() => expect(startedRun()).not.toBeNull());

    const [path, init] = fetchMock.mock.calls[1];
    expect(path).toBe("/products/wasifyai-image/uploads/images");
    expect((init.body as File).name).toBe("mask.png");
    expect((init.body as File).type).toBe("image/png");
    expect(startedRun()).toMatchObject({
      mode: "inpaint",
      prompt: "a white cup",
      image_key: "uploads/u1.png",
      mask_key: "uploads/u2.png",
    });
    expect(startedRun()).not.toHaveProperty("size");
  });

  it("says so when the painted area cannot be sent, and starts no run", async () => {
    const user = userEvent.setup({ applyAccept: false });
    await withPicture(user);
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: "That file is too big." }, { status: 413 }),
    );
    await user.type(screen.getByRole("textbox"), "a white cup");
    await paintRectangle(user);
    await user.click(await screen.findByRole("button", { name: "Make the picture" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(startedRun()).toBeNull();
    expect(screen.getByRole("button", { name: "Make the picture" })).toBeEnabled(); // and it can be tried again
  });
});

describe("the recipe of an image made another way", () => {
  it("names how a reference and an inpaint image were made", async () => {
    const recent: ImageSummary[] = (["reference", "inpaint"] as const).map((mode, n) => ({
      id: `i${n}`,
      prompt: `a ${mode} image`,
      mode,
      width: 1024,
      height: 1024,
      created_at: "2026-10-15T08:00:00Z",
      image_url: "http://127.0.0.1:1/files/i.png",
      thumb_url: "http://127.0.0.1:1/files/t.jpg",
      recipe: { v: 1, mode, prompt: "x", size: null, width: 1024, height: 1024, seed: 1 },
      favourite: false,
    }));
    const listing = {
      ...api,
      async list() {
        return { images: recent, next_before: null };
      },
    };
    const user = userEvent.setup();
    render(<ImageWorkspace mode="text" runs={runs} images={listing} />);
    await user.click(await screen.findByRole("button", { name: "Open: a inpaint image" }));
    await user.click(screen.getByRole("button", { name: /Recipe/ }));
    expect(screen.getByText("Change of a painted area")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open: a reference image" }));
    expect(screen.getByText("Made from two pictures")).toBeInTheDocument();
  });
});
