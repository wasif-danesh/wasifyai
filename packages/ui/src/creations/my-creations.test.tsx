import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
// @vitest-environment jsdom
import type { CreationsApi, ImageSummary, Recent, VideoSummary } from "@wasifyai/client";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { MyCreations } from "./MyCreations";
import type { CreationsNav } from "./model";

// Radix's pointer handling and the media element need these in jsdom
beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
  window.HTMLMediaElement.prototype.pause = vi.fn();
});

const when = "2026-10-20T10:00:00Z";
const NONE = { models3d: [], compositions: [], notebooks: [], taught: [] };

const picture = (over: Partial<ImageSummary> = {}): ImageSummary => ({
  id: "i1",
  prompt: "A teapot",
  mode: "text",
  width: 64,
  height: 64,
  created_at: when,
  image_url: "http://x/i1.png",
  thumb_url: "http://x/i1.jpg",
  recipe: null,
  favourite: false,
  source_id: null,
  ...over,
});

const clip = (over: Partial<VideoSummary> = {}): VideoSummary => ({
  id: "v1",
  prompt: "Steam rises",
  mode: "image",
  status: "done",
  seconds: 5,
  created_at: "2026-10-21T10:00:00Z",
  width: 64,
  height: 64,
  error: null,
  video_url: "http://x/v1.mp4",
  poster_url: "http://x/v1.jpg",
  source_id: null,
  ...over,
});

const recent = (over: Partial<Recent> = {}): Recent => ({
  images: null,
  videos: null,
  songs: [{ id: "k1", title: "Rainy day", style: "soft piano", created_at: when, audio_url: "a" }],
  speeches: [],
  transcripts: [],
  lipsyncs: [],
  others: NONE,
  failed: [],
  ...over,
});

const api = (r: Promise<Recent>, over: Partial<CreationsApi> = {}): CreationsApi => ({
  recent: () => r,
  moreImages: async () => ({ images: [], next_before: null }),
  moreVideos: async () => ({ videos: [], next_before: null }),
  search: async () => ({ query: "", degraded: false, results: [] }),
  cards: async () => ({
    images: null,
    videos: null,
    songs: [],
    speeches: [],
    transcripts: [],
    lipsyncs: [],
    others: NONE,
  }),
  madeFrom: async () => ({ images: [], videos: [], songs: [] }),
  remove: vi.fn(async () => undefined),
  addRecording: vi.fn(),
  ...over,
});

/** Run an action of the detail view: one of its buttons, or an item of its More menu. */
async function act(detail: HTMLElement, name: RegExp) {
  const button = within(detail).queryByRole("button", { name });
  if (button) return userEvent.click(button);
  await userEvent.click(within(detail).getByRole("button", { name: "More" }));
  await userEvent.click(await screen.findByRole("menuitem", { name }));
}

const nav = (over: Partial<CreationsNav> = {}): CreationsNav => ({
  open: vi.fn(),
  make: vi.fn(),
  ...over,
});

describe("the Library", () => {
  it("opens a card in place, and Open in its tool goes where the app says", async () => {
    const n = nav();
    const user = userEvent.setup();
    render(<MyCreations api={api(Promise.resolve(recent()))} nav={n} />);
    await user.click(await screen.findByRole("link", { name: /Rainy day/ }));
    const detail = await screen.findByRole("dialog", { name: "Rainy day" });
    expect(n.open).not.toHaveBeenCalled();
    await act(detail, /Open in its tool/);
    expect(n.open).toHaveBeenCalledWith(expect.objectContaining({ kind: "song", id: "k1" }));
  });

  it("offers the screens that make something new when there is nothing yet", async () => {
    const n = nav();
    render(
      <MyCreations
        api={api(
          Promise.resolve(
            recent({
              songs: [],
              images: { images: [], next_before: null },
              videos: { videos: [], next_before: null },
            }),
          ),
        )}
        nav={n}
      />,
    );
    await userEvent.click(await screen.findByRole("link", { name: "Make an image" }));
    expect(n.make).toHaveBeenCalledWith("image");
  });

  it("says so when the service does not answer, and when one kind could not be read", async () => {
    render(<MyCreations api={api(Promise.reject(new Error("down")))} nav={nav()} />);
    expect(await screen.findByText("Couldn't load your creations")).toBeInTheDocument();
    render(<MyCreations api={api(Promise.resolve(recent({ failed: ["images"] })))} nav={nav()} />);
    expect(await screen.findByText("Couldn't load your images")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Rainy day/ })).toBeInTheDocument();
  });

  it("shows where a picture came from and what was made from it, each opening here", async () => {
    const first = picture({ id: "i1", prompt: "A teapot" });
    const edited = picture({ id: "i2", prompt: "A blue teapot", mode: "image", source_id: "i1" });
    const animated = clip({ id: "v1", source_id: "i1" });
    const user = userEvent.setup();
    const a = api(
      Promise.resolve(
        recent({ songs: [], images: { images: [edited, first], next_before: null } }),
      ),
      {
        cards: async (ids) => ({
          images: { images: ids.image?.includes("i1") ? [first] : [], next_before: null },
          videos: null,
          songs: [],
          speeches: [],
          transcripts: [],
          lipsyncs: [],
          others: NONE,
        }),
        madeFrom: vi.fn(async (_kind, id) =>
          id === "i1"
            ? { images: [edited], videos: [animated], songs: [] }
            : { images: [], videos: [], songs: [] },
        ),
      },
    );
    render(<MyCreations api={a} nav={nav()} />);
    await user.click(await screen.findByRole("link", { name: /A blue teapot/ }));
    const detail = await screen.findByRole("dialog");
    const from = await within(detail).findByRole("region", { name: "Made from" });
    await user.click(await within(from).findByRole("button", { name: "Open: A teapot" }));
    // the source opens here, with what was made from it
    const made = await screen.findByRole("region", { name: "Made from this" });
    expect(within(made).getByRole("button", { name: "Open: A blue teapot" })).toBeInTheDocument();
    expect(within(made).getByRole("button", { name: "Open: Steam rises" })).toBeInTheDocument();
    expect(a.madeFrom).toHaveBeenCalledWith("image", "i1");
  });

  it("hands a picture to Edit and Animate, and a clip to Extend, only through the app", async () => {
    const use = vi.fn();
    const n = nav({ use, canUse: (entry) => entry.kind === "image" || entry.kind === "video" });
    const user = userEvent.setup();
    render(
      <MyCreations
        api={api(
          Promise.resolve(
            recent({
              songs: [],
              images: { images: [picture()], next_before: null },
              videos: { videos: [clip()], next_before: null },
            }),
          ),
        )}
        nav={n}
      />,
    );
    await user.click(await screen.findByRole("link", { name: /A teapot/ }));
    let detail = await screen.findByRole("dialog");
    await user.click(within(detail).getByRole("button", { name: /Animate this/ }));
    expect(use).toHaveBeenCalledWith(expect.objectContaining({ kind: "image" }), "animate");
    await user.click(within(detail).getByRole("button", { name: /Edit this/ }));
    expect(use).toHaveBeenCalledWith(expect.objectContaining({ kind: "image" }), "edit");
    await user.keyboard("{Escape}");
    await user.click(await screen.findByRole("link", { name: /Steam rises/ }));
    detail = await screen.findByRole("dialog");
    await user.click(within(detail).getByRole("button", { name: /Extend this/ }));
    expect(use).toHaveBeenCalledWith(expect.objectContaining({ kind: "video" }), "extend");
  });

  it("deletes one after asking, and takes it off the list", async () => {
    const remove = vi.fn(async () => undefined);
    const user = userEvent.setup();
    render(<MyCreations api={api(Promise.resolve(recent()), { remove })} nav={nav()} />);
    await user.click(await screen.findByRole("link", { name: /Rainy day/ }));
    const detail = await screen.findByRole("dialog", { name: "Rainy day" });
    await act(detail, /Delete/);
    expect(remove).not.toHaveBeenCalled();
    const ask = await screen.findByRole("dialog", { name: /Delete this music/ });
    await user.click(within(ask).getByRole("button", { name: "Delete" }));
    expect(remove).toHaveBeenCalledWith("track", "k1");
    await waitFor(() => expect(screen.queryByRole("link", { name: /Rainy day/ })).toBeNull());
  });

  it("chooses several and deletes them together, and sorts by name", async () => {
    const remove = vi.fn(async () => undefined);
    const user = userEvent.setup();
    const songs = [
      {
        id: "k1",
        title: "Rainy day",
        style: "",
        created_at: "2026-10-20T10:00:00Z",
        audio_url: "a",
      },
      { id: "k2", title: "Autumn", style: "", created_at: "2026-10-21T10:00:00Z", audio_url: "b" },
      { id: "k3", title: "Morning", style: "", created_at: "2026-10-22T10:00:00Z", audio_url: "c" },
    ];
    render(<MyCreations api={api(Promise.resolve(recent({ songs })), { remove })} nav={nav()} />);
    await screen.findByRole("link", { name: /Morning/ });
    const titles = () =>
      screen
        .getAllByRole("link")
        .map((l) => l.textContent ?? "")
        .filter((t) => /Rainy|Autumn|Morning/.test(t));
    expect(titles()[0]).toContain("Morning"); // newest first
    await user.click(screen.getByRole("combobox", { name: "Sort" }));
    await user.click(await screen.findByRole("option", { name: "A to Z" }));
    expect(titles()[0]).toContain("Autumn");

    await user.click(screen.getByRole("button", { name: /Select/ }));
    await user.click(screen.getByRole("checkbox", { name: /Choose Autumn/ }));
    await user.click(screen.getByRole("link", { name: /Morning/ })); // a card chooses while choosing
    expect(screen.getByText("2 chosen")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Delete$/ }));
    const ask = await screen.findByRole("dialog", { name: "Delete these 2?" });
    await user.click(within(ask).getByRole("button", { name: "Delete" }));
    expect(remove.mock.calls).toEqual([
      ["track", "k2"],
      ["track", "k3"],
    ]);
    await waitFor(() => expect(screen.queryByRole("link", { name: /Autumn/ })).toBeNull());
    expect(screen.getByRole("link", { name: /Rainy day/ })).toBeInTheDocument();
  });

  it("lists the tools' own kinds with a filter once there is one", async () => {
    const user = userEvent.setup();
    const others = {
      ...NONE,
      notebooks: [
        {
          id: "n1",
          title: "Launch plan",
          created_at: when,
          updated_at: when,
          opened_at: null,
          sources: 3,
          ready: 3,
          reading: 0,
          failed: 0,
        },
      ],
    };
    render(<MyCreations api={api(Promise.resolve(recent({ others })))} nav={nav()} />);
    expect(await screen.findByRole("link", { name: /Launch plan/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /3D models/ })).toBeNull(); // none: no filter
    await user.click(screen.getByRole("button", { name: /Notebooks/ }));
    expect(screen.queryByRole("link", { name: /Rainy day/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Launch plan/ })).toBeInTheDocument();
  });
});
