import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
// @vitest-environment jsdom
import type { CreationsApi, Recent } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { MyCreations } from "./MyCreations";
import type { CreationsNav } from "./model";

const when = "2026-10-20T10:00:00Z";
const recent = (over: Partial<Recent> = {}): Recent => ({
  images: null,
  videos: null,
  songs: [{ id: "k1", title: "Rainy day", style: "soft piano", created_at: when, audio_url: "a" }],
  speeches: [],
  transcripts: [],
  lipsyncs: [],
  failed: [],
  ...over,
});
const api = (r: Promise<Recent>): CreationsApi => ({
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
  }),
});
const nav = (): CreationsNav => ({ open: vi.fn(), make: vi.fn() });

describe("My creations", () => {
  it("lists what was made, and opening a card goes where the app says", async () => {
    const n = nav();
    render(<MyCreations api={api(Promise.resolve(recent()))} nav={n} />);
    const card = await screen.findByRole("link", { name: /Rainy day/ });
    await userEvent.click(card);
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
});
