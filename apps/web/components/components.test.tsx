// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LyricSheet } from "./LyricSheet";
import { NavLink } from "./NavLink";
import { SongView } from "./SongView";

const pathname = vi.hoisted(() => ({ value: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.value }));

const LYRICS = "[verse]\nline one\nline two\n\n[chorus]\nsing it";

describe("LyricSheet", () => {
  it("sets lyrics out by section, with the chorus marked", () => {
    const { container } = render(<LyricSheet text={LYRICS} />);
    expect(screen.getByText("Verse")).toBeInTheDocument();
    expect(screen.getByText("Chorus")).toBeInTheDocument();
    expect(container.querySelector('[data-tag="chorus"]')).toHaveTextContent("sing it");
  });

  it("shows a caret only while streaming, and a waiting line when empty", () => {
    const { container, rerender } = render(<LyricSheet text={LYRICS} streaming />);
    expect(container.querySelector("[data-caret]")).not.toBeNull();
    rerender(<LyricSheet text={LYRICS} />);
    expect(container.querySelector("[data-caret]")).toBeNull();
    rerender(<LyricSheet text="" streaming />);
    expect(screen.getByText(/waiting for the first line/i)).toBeInTheDocument();
  });
});

describe("SongView", () => {
  const song = {
    title: "Neon Rain!",
    style: "synth-pop, upbeat",
    lyrics: LYRICS,
    audioUrl: "http://s/a/song.mp3?sig=1",
    coverUrl: "http://s/a/cover.png?sig=1",
  };

  it("downloads from the app's own origin when the song has an id, so browsers save the file", () => {
    render(<SongView song={{ ...song, songId: "3f2b8c1e-0000-4000-8000-000000000001" }} />);
    expect(screen.getByRole("link", { name: "Download audio" })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-music/songs/3f2b8c1e-0000-4000-8000-000000000001/download/audio",
    );
    expect(screen.getByRole("link", { name: "Download cover" })).toHaveAttribute(
      "href",
      "/api/products/wasifyai-music/songs/3f2b8c1e-0000-4000-8000-000000000001/download/cover",
    );
    // playing and showing still use the storage links
    expect(screen.getByRole("img", { name: /Cover art/ })).toHaveAttribute("src", song.coverUrl);
  });

  it("offers the video download next to audio and cover, when there is a cover and an id", () => {
    render(<SongView song={{ ...song, songId: "3f2b8c1e-0000-4000-8000-000000000001" }} />);
    const video = screen.getByRole("link", { name: "Download video" });
    expect(video).toHaveAttribute(
      "href",
      "/api/products/wasifyai-music/songs/3f2b8c1e-0000-4000-8000-000000000001/download/video",
    );
    expect(video).toHaveAttribute("download", "neon-rain.mp4");
  });

  it("offers no video without a cover or without an id", () => {
    const withId = { ...song, songId: "3f2b8c1e-0000-4000-8000-000000000001" };
    const { rerender } = render(<SongView song={{ ...withId, coverUrl: null }} />);
    expect(screen.queryByRole("link", { name: "Download video" })).not.toBeInTheDocument();
    rerender(<SongView song={song} />);
    expect(screen.queryByRole("link", { name: "Download video" })).not.toBeInTheDocument();
  });

  it("falls back to the storage link when there is no song id", () => {
    render(<SongView song={song} />);
    expect(screen.getByRole("link", { name: "Download audio" })).toHaveAttribute(
      "href",
      song.audioUrl,
    );
  });

  it("shows the cover, tags, player and downloads with readable file names", () => {
    render(<SongView song={song} />);
    expect(screen.getByRole("img", { name: "Cover art for Neon Rain!" })).toHaveAttribute(
      "src",
      song.coverUrl,
    );
    expect(screen.getByText("synth-pop")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download audio" })).toHaveAttribute(
      "download",
      "neon-rain.mp3",
    );
    expect(screen.getByRole("link", { name: "Download cover" })).toHaveAttribute(
      "download",
      "neon-rain.png",
    );
  });

  it("copes with a song whose cover failed", () => {
    render(<SongView song={{ ...song, coverUrl: null }} />);
    expect(screen.getByRole("img", { name: "No cover art" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download cover" })).toBeNull();
  });

  it("uses the heading level the page asks for", () => {
    render(<SongView song={song} heading="h1" />);
    expect(screen.getByRole("heading", { level: 1, name: "Neon Rain!" })).toBeInTheDocument();
  });
});

describe("NavLink", () => {
  it("marks the current page, including its sub-pages", () => {
    pathname.value = "/songs/abc";
    render(
      <>
        <NavLink href="/">Create</NavLink>
        <NavLink href="/songs">My songs</NavLink>
      </>,
    );
    expect(screen.getByRole("link", { name: "My songs" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Create" })).not.toHaveAttribute("aria-current");
  });

  it("only marks the home link on exactly the home page", () => {
    pathname.value = "/";
    render(<NavLink href="/">Create</NavLink>);
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute("aria-current", "page");
  });
});
