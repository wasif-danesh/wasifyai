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
    expect(screen.getByText("7")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /use a new one/i }));
    expect(screen.queryByText("7")).not.toBeInTheDocument();
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

  it("allows three styles and no more", async () => {
    const user = userEvent.setup();
    render(
      <ImageWorkspace
        mode="text"
        runs={runs}
        images={fakeApi([])}
        loras={["a", "b", "c", "d"].map((n) => ({ name: `${n}.safetensors`, title: n }))}
        preset={{ prompt: "x", size: null, seed: 1, loras: [] }}
      />,
    );
    for (const n of ["a", "b", "c"]) await user.click(screen.getByRole("checkbox", { name: n }));
    expect(screen.getByRole("checkbox", { name: "d" })).toBeDisabled();
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
