// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type ImageSummary, type ImagesApi, createRunClient } from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { done, node, sse } from "../test-utils";
import { ImageLibrary } from "./ImageLibrary";
import { ImageWorkspace, presetOf } from "./ImageWorkspace";

const fetchMock = vi.fn();
const runs = createRunClient({ fetch: (path, init) => fetchMock(path, init) });

function summary(over: Partial<ImageSummary> = {}): ImageSummary {
  return {
    id: "i1",
    prompt: "a lighthouse",
    mode: "text",
    width: 1024,
    height: 1024,
    created_at: "2026-10-15T08:00:00Z",
    image_url: "http://127.0.0.1:1/files/i1.png",
    thumb_url: "http://127.0.0.1:1/files/t1.jpg",
    recipe: {
      v: 1,
      mode: "text",
      prompt: "a lighthouse",
      size: "wide",
      width: 1344,
      height: 768,
      seed: 4242,
    },
    favourite: false,
    ...over,
  };
}

function fakeApi(items: ImageSummary[]): ImagesApi & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    async list(o = {}) {
      calls.push(`list${o.favourites ? ":fav" : ""}`);
      const rows = o.favourites ? items.filter((i) => i.favourite) : items;
      return { images: rows, next_before: null };
    },
    async search() {
      return [];
    },
    async get(id) {
      const found = items.find((i) => i.id === id);
      if (!found) throw new Error("missing");
      return found;
    },
    async remove(id) {
      calls.push(`remove:${id}`);
    },
    async setFavourite(id, favourite) {
      calls.push(`favourite:${id}:${favourite}`);
      const i = items.findIndex((x) => x.id === id);
      items[i] = { ...items[i], favourite } as ImageSummary;
      return items[i] as ImageSummary;
    },
    async exportCopy(id) {
      calls.push(`export:${id}`);
      return { name: "a-lighthouse.png", path: "/Users/me/Downloads/a-lighthouse.png" };
    },
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  sessionStorage.clear();
});

describe("presetOf", () => {
  it("is there for a text image with a recipe, and only then", () => {
    expect(presetOf(summary())).toEqual({
      prompt: "a lighthouse",
      size: "wide",
      seed: 4242,
      loras: [],
      styles: [],
      steps: null,
      own: null,
    });
    expect(presetOf(summary({ recipe: null }))).toBeNull();
    expect(presetOf(summary({ mode: "image" }))).toBeNull();
  });
});

describe("ImageWorkspace", () => {
  it("makes an image, then favourites it and saves a copy", async () => {
    const api = fakeApi([summary()]);
    fetchMock.mockResolvedValueOnce(
      sse([
        node("check_request"),
        done({
          status: "done",
          image_id: "i1",
          image_url: "http://127.0.0.1:1/files/i1.png",
          thumb_url: "http://127.0.0.1:1/files/t1.jpg",
          width: 1024,
          height: 1024,
          prompt: "a lighthouse",
          mode: "text",
        }),
      ]),
    );
    const user = userEvent.setup();
    render(<ImageWorkspace mode="text" runs={runs} images={api} canSave />);
    await user.type(screen.getByRole("textbox"), "a lighthouse");
    await user.click(screen.getByRole("button", { name: "Make the picture" }));

    expect(await screen.findByRole("img", { name: "a lighthouse" })).toBeInTheDocument();
    // the full record arrives: the recipe is there to show and to run again
    await screen.findByRole("button", { name: /make it again/i });

    // three actions stay as buttons; the rest are behind More (ADR-0093 decision 8)
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: /add to favourites/i }));
    await waitFor(() => expect(api.calls).toContain("favourite:i1:true"));
    await user.click(screen.getByRole("button", { name: "More" }));
    expect(
      await screen.findByRole("menuitem", { name: /remove from favourites/i }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: /save a copy/i }));
    expect(await screen.findByText("Saved as a-lighthouse.png in Downloads.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: /^recipe$/i }));
    expect(screen.getByText("4242")).toBeInTheDocument();
  });

  it("keeps the heart when the full record arrives after it was pressed", async () => {
    // a slow computer: the picture is shown from the run's result, and the full record (read on the
    // side) comes back only after the person pressed the heart. It was made before the press, so it
    // says "not a favourite", and must not undo it.
    const items = [summary()];
    const api = fakeApi(items);
    let release: () => void = () => undefined;
    const late = new Promise<void>((r) => {
      release = r;
    });
    api.get = async (id) => {
      const before = { ...(items.find((i) => i.id === id) as ImageSummary) };
      await late;
      return before;
    };
    fetchMock.mockResolvedValueOnce(
      sse([
        done({
          status: "done",
          image_id: "i1",
          image_url: "http://127.0.0.1:1/files/i1.png",
          thumb_url: "http://127.0.0.1:1/files/t1.jpg",
          width: 1024,
          height: 1024,
          prompt: "a lighthouse",
          mode: "text",
        }),
      ]),
    );
    const user = userEvent.setup();
    render(<ImageWorkspace mode="text" runs={runs} images={api} />);
    await user.type(screen.getByRole("textbox"), "a lighthouse");
    await user.click(screen.getByRole("button", { name: "Make the picture" }));
    // with no recipe yet there are three actions, so the heart is a button, not a menu item
    await user.click(await screen.findByRole("button", { name: /add to favourites/i }));
    await waitFor(() => expect(api.calls).toContain("favourite:i1:true"));
    expect(await screen.findByText(/· favourite/)).toBeInTheDocument();
    release();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText(/· favourite/)).toBeInTheDocument(); // the stage's caption still says so
  });

  it("makes it again with the same prompt, size and seed", async () => {
    const api = fakeApi([summary()]);
    fetchMock.mockResolvedValueOnce(sse([node("check_request")]));
    const user = userEvent.setup();
    render(<ImageWorkspace mode="text" runs={runs} images={api} />);

    await user.click(await screen.findByRole("button", { name: "Open: a lighthouse" }));
    await user.click(screen.getByRole("button", { name: /make it again/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/products/wasifyai-image/runs");
    expect(JSON.parse(String(init.body)).input).toEqual({
      mode: "text",
      prompt: "a lighthouse",
      size: "wide",
      seed: 4242,
    });
  });

  it("starts from a recipe it is given and can drop its seed", async () => {
    fetchMock.mockResolvedValue(sse([node("check_request")]));
    const user = userEvent.setup();
    render(
      <ImageWorkspace
        mode="text"
        runs={runs}
        images={fakeApi([])}
        preset={{ prompt: "a fox", size: "tall", seed: 7, loras: [] }}
      />,
    );
    expect(screen.getByRole("textbox")).toHaveValue("a fox");
    const seed = screen.getByRole("spinbutton", { name: "Seed" });
    expect(seed).toHaveValue(7);

    await user.clear(seed); // empty: a new seed
    expect(seed).toHaveValue(null);
    await user.click(screen.getByRole("button", { name: "Make the picture" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).input).toEqual({
      mode: "text",
      prompt: "a fox",
      size: "tall",
    });
  });
});

describe("ImageLibrary", () => {
  it("filters favourites, toggles a heart, and asks before deleting", async () => {
    const items = [
      summary({ id: "a", prompt: "first" }),
      summary({ id: "b", prompt: "second", favourite: true }),
    ];
    const api = fakeApi(items);
    const again = vi.fn();
    const user = userEvent.setup();
    render(<ImageLibrary images={api} onRunAgain={again} canSave />);

    expect(await screen.findAllByRole("button", { name: /^Open:/ })).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Favourites" }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: /^Open:/ })).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Open: second" })).toBeInTheDocument();

    // un-favouriting in the favourites view takes it out of the list
    await user.click(screen.getByRole("button", { name: "Open: second" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Favourite" }));
    await waitFor(() => expect(api.calls).toContain("favourite:b:false"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Open: second" })).toBeNull());

    // make it again hands the image to the app; delete needs the second click
    await user.click(screen.getByRole("button", { name: "All" }));
    await user.click(await screen.findByRole("button", { name: "Open: first" }));
    await user.click(screen.getByRole("button", { name: /make it again/i }));
    expect(again).toHaveBeenCalledWith(expect.objectContaining({ id: "a" }));

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(api.calls.some((c) => c.startsWith("remove"))).toBe(false);
    await user.click(screen.getByRole("button", { name: /yes, delete it/i }));
    await waitFor(() => expect(api.calls).toContain("remove:a"));
  });

  it("says so when there are no favourites", async () => {
    const user = userEvent.setup();
    render(<ImageLibrary images={fakeApi([summary()])} />);
    await user.click(await screen.findByRole("button", { name: "Favourites" }));
    expect(await screen.findByText(/no favourites yet/i)).toBeInTheDocument();
  });
});

describe("ImageWorkspace when the model cannot run", () => {
  it("keeps Generate off and says why", async () => {
    const user = userEvent.setup();
    render(
      <ImageWorkspace
        mode="text"
        runs={runs}
        images={fakeApi([])}
        blockedReason="The model will not fit. It needs about 24 GB."
      />,
    );
    await user.type(screen.getByRole("textbox"), "a lighthouse");
    expect(screen.getByRole("button", { name: "Make the picture" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("will not fit");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("styles, Vary and the edit source", () => {
  const withStyles = summary({
    recipe: {
      v: 1,
      mode: "text",
      prompt: "a lighthouse",
      size: "wide",
      width: 1344,
      height: 768,
      seed: 4242,
      loras: [{ name: "ink.safetensors", weight: 0.8 }],
    },
  }); // fmt: skip

  it("sends the styles that were chosen, with their strength", async () => {
    fetchMock.mockResolvedValue(sse([node("check_request")]));
    const user = userEvent.setup();
    render(
      <ImageWorkspace
        mode="text"
        runs={runs}
        images={fakeApi([])}
        loras={[
          { name: "ink.safetensors", title: "Ink" },
          { name: "film.safetensors", title: "Film" },
        ]}
      />,
    );
    await user.click(screen.getByRole("checkbox", { name: "Ink" }));
    const slider = screen.getByRole("slider", { name: "Strength of Ink" });
    slider.focus();
    await user.keyboard("{ArrowLeft}".repeat(8)); // 1.00 down to 0.60, a step of 0.05 at a time
    await user.type(screen.getByRole("textbox", { name: /prompt/i }), "a fox");
    await user.click(screen.getByRole("button", { name: "Make the picture" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).input.loras).toEqual([
      { name: "ink.safetensors", weight: 0.6 },
    ]);
  });

  it("allows eight styles and no more", async () => {
    const user = userEvent.setup();
    const names = ["a", "b", "c", "d", "e", "f", "g", "h", "i"];
    render(
      <ImageWorkspace
        mode="text"
        runs={runs}
        images={fakeApi([])}
        loras={names.map((n) => ({ name: `${n}.safetensors`, title: n }))}
        preset={{ prompt: "x", size: null, seed: 1, loras: [] }}
      />,
    );
    for (const n of names.slice(0, 8)) await user.click(screen.getByRole("checkbox", { name: n }));
    expect(screen.getByRole("checkbox", { name: "i" })).toBeDisabled();
  });

  it("on the desktop, styles are always in view and go to the engine by id", async () => {
    fetchMock.mockResolvedValue(sse([node("check_request")]));
    const user = userEvent.setup();
    const ink = {
      id: "a1",
      title: "Ink",
      source: { kind: "file" as const },
      sha256: "x",
      size: 1,
      model: "FLUX.2 klein 4B",
      fit: "fits" as const,
      made_for_base: false,
      rank: 16,
      unused_parts: 0,
      trigger: "inkwash",
      added_at: 1,
      selectable: true,
    };
    const stylesApi = {
      list: vi.fn(async () => ({ styles: [ink], found: [], max: 8 })),
    } as never;
    render(
      <ImageWorkspace
        mode="text"
        runs={runs}
        images={fakeApi([])}
        stylesApi={stylesApi}
        preset={{
          prompt: "a fox",
          size: null,
          seed: null,
          loras: [],
          styles: [{ id: "a1", strength: 0.7 }],
        }}
      />,
    ); // fmt: skip
    await user.click(await screen.findByRole("button", { name: "Use this word" }));
    expect(screen.getByRole("textbox", { name: /prompt/i })).toHaveValue("a fox, inkwash");
    await user.click(screen.getByRole("button", { name: "Make the picture" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const input = JSON.parse(String(init.body)).input;
    expect(input.styles).toEqual([{ id: "a1", strength: 0.7 }]);
    expect(input.loras).toBeUndefined();
  });

  it("offers a style that is one click away, and does it", async () => {
    const onUse = vi.fn(async () => {});
    const user = userEvent.setup();
    render(
      <ImageWorkspace
        mode="text"
        runs={runs}
        images={fakeApi([])}
        availableLoras={[{ id: "l1", name: "ink.safetensors", title: "Ink" }]}
        onUseLora={onUse}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Use it" }));
    expect(onUse).toHaveBeenCalledWith("l1");
  });

  it("makes a variation: the same recipe and styles with a new seed", async () => {
    fetchMock.mockResolvedValue(sse([node("check_request")]));
    const user = userEvent.setup();
    render(
      <ImageWorkspace
        mode="text"
        runs={runs}
        images={fakeApi([withStyles])}
        loras={[{ name: "ink.safetensors", title: "Ink" }]}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Open: a lighthouse" }));
    await user.click(screen.getByRole("button", { name: /vary/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).input).toEqual({
      mode: "text",
      prompt: "a lighthouse",
      size: "wide",
      loras: [{ name: "ink.safetensors", weight: 0.8 }],
    }); // no seed: the engine draws a new one
  });

  it("make it again keeps the seed and the styles", async () => {
    fetchMock.mockResolvedValue(sse([node("check_request")]));
    const user = userEvent.setup();
    render(<ImageWorkspace mode="text" runs={runs} images={fakeApi([withStyles])} />);
    await user.click(await screen.findByRole("button", { name: "Open: a lighthouse" }));
    await user.click(screen.getByRole("button", { name: /make it again/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).input).toEqual({
      mode: "text",
      prompt: "a lighthouse",
      size: "wide",
      seed: 4242,
      loras: [{ name: "ink.safetensors", weight: 0.8 }],
    });
  });

  it("hands a result to Edit, and lists the styles in the recipe", async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    render(
      <ImageWorkspace mode="text" runs={runs} images={fakeApi([withStyles])} onEditThis={onEdit} />,
    );
    await user.click(await screen.findByRole("button", { name: "Open: a lighthouse" }));
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: /^recipe$/i }));
    expect(screen.getByText("ink.safetensors (0.8)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^edit this$/i }));
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: "i1" }));
  });

  it("hands a result to Video's Animate, next to Edit this", async () => {
    const onAnimate = vi.fn();
    const user = userEvent.setup();
    render(
      <ImageWorkspace
        mode="text"
        runs={runs}
        images={fakeApi([summary()])}
        onEditThis={vi.fn()}
        onAnimateThis={onAnimate}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Open: a lighthouse" }));
    const row = within(screen.getByRole("region", { name: "Result" }));
    const buttons = row.getAllByRole("button").map((b) => b.textContent);
    expect(buttons.slice(0, 2)).toEqual(["Edit this", "Animate this"]);
    await user.click(row.getByRole("button", { name: /^animate this$/i }));
    expect(onAnimate).toHaveBeenCalledWith(expect.objectContaining({ id: "i1" }));
  });
});

describe("where an edit came from", () => {
  it("sends the library picture Edit this handed over, and nothing for a file of the person's own", async () => {
    const realFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => ({
      blob: async () => new Blob(["x"], { type: "image/png" }),
    })) as unknown as typeof fetch;
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
    try {
      for (const replace of [false, true]) {
        fetchMock.mockReset();
        let n = 0;
        fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
          if (path === "/products/wasifyai-image/runs") {
            return sse([
              done({
                status: "done",
                image_id: "new",
                image_url: "http://x/new.png",
                thumb_url: "http://x/new.jpg",
                width: 64,
                height: 64,
                prompt: "x",
                mode: "image",
              }),
            ]); // fmt: skip
          }
          if (init?.method === "DELETE") return new Response(null, { status: 204 });
          n += 1;
          return new Response(
            JSON.stringify({
              upload_id: `u${n}`,
              key: `uploads/u${n}.png`,
              width: 8,
              height: 8,
              bytes: 1,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        });
        const user = userEvent.setup({ applyAccept: false });
        const { unmount } = render(
          <ImageWorkspace
            mode="image"
            runs={runs}
            images={fakeApi([summary()])}
            sourceImage={{ url: "http://x/i1.png", name: "i1.png", id: "i1" }}
          />,
        );
        await screen.findByRole("button", { name: /Replace/ });
        if (replace) {
          await user.upload(
            screen.getByLabelText("Your picture"),
            new File(["y"], "mine.png", { type: "image/png" }),
          );
          await waitFor(() => expect(n).toBe(2));
        }
        await user.type(screen.getByRole("textbox"), "make it blue");
        await user.click(screen.getByRole("button", { name: "Make the picture" }));
        await waitFor(() =>
          expect(fetchMock.mock.calls.some((c) => c[0] === "/products/wasifyai-image/runs")).toBe(
            true,
          ),
        );
        const run = fetchMock.mock.calls.find((c) => c[0] === "/products/wasifyai-image/runs");
        const input = JSON.parse(String(run?.[1]?.body)).input;
        if (replace) expect(input).not.toHaveProperty("source_id");
        else expect(input.source_id).toBe("i1");
        unmount();
      }
    } finally {
      globalThis.fetch = realFetch;
    }
  });

  it("Advanced: steps and a size of one's own go to the engine, and several pictures follow one another", async () => {
    let n = 0;
    fetchMock.mockImplementation(async () => {
      n += 1;
      return sse([
        node("check_request"),
        done({
          status: "done",
          image_id: `i${n}`,
          image_url: "x",
          thumb_url: "x",
          width: 1280,
          height: 720,
          prompt: "a fox",
          mode: "text",
        }),
      ]);
    }); // fmt: skip
    const user = userEvent.setup();
    render(<ImageWorkspace mode="text" runs={runs} images={fakeApi([])} />);
    await user.type(screen.getByRole("textbox", { name: /prompt/i }), "a fox");
    await user.click(screen.getByText("Advanced"));
    await user.type(screen.getByRole("spinbutton", { name: "Steps" }), "8");
    await user.type(screen.getByRole("spinbutton", { name: "Seed" }), "41");
    await user.type(screen.getByRole("spinbutton", { name: "Width" }), "1280");
    await user.type(screen.getByRole("spinbutton", { name: "Height" }), "720");
    expect(screen.getByText("1280 × 720, instead of the shape above.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "3" }));
    await user.click(screen.getByRole("button", { name: "Make the picture" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3), { timeout: 4000 });
    const inputs = fetchMock.mock.calls.map(
      ([, init]) => JSON.parse(String((init as RequestInit).body)).input,
    );
    expect(inputs.map((i) => [i.seed, i.steps, i.width, i.height])).toEqual([
      [41, 8, 1280, 720],
      [42, 8, 1280, 720],
      [43, 8, 1280, 720],
    ]); // fmt: skip
  });

  it("Advanced: a size off the grid is said and not sent", async () => {
    fetchMock.mockResolvedValue(sse([node("check_request")]));
    const user = userEvent.setup();
    render(<ImageWorkspace mode="text" runs={runs} images={fakeApi([])} />);
    await user.type(screen.getByRole("textbox", { name: /prompt/i }), "a fox");
    await user.click(screen.getByText("Advanced"));
    await user.type(screen.getByRole("spinbutton", { name: "Width" }), "1000");
    await user.type(screen.getByRole("spinbutton", { name: "Height" }), "700");
    expect(screen.getByText(/in steps of 16/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Make the picture" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).input.width).toBeUndefined();
  });
});
