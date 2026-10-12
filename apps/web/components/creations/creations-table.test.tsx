import type { Entry } from "@/lib/creations";
// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SongSummary, SpeechSummary } from "@wasifyai/contracts";
import { describe, expect, it } from "vitest";
import { CreationsTable } from "./CreationsTable";

const song = (id: string, title: string, createdAt: string): Entry => ({
  kind: "song",
  id,
  createdAt,
  song: { id, title, style: "lo-fi", created_at: createdAt } as unknown as SongSummary,
});
const speech: Entry = {
  kind: "speech",
  id: "s1",
  createdAt: "2026-10-03T10:00:00Z",
  speech: {
    id: "s1",
    text: "আপনি কেমন আছেন?",
    language: "bn",
    language_name: "বাংলা",
    gender: "female",
    voice: "Aditi",
    created_at: "2026-10-03T10:00:00Z",
  } as unknown as SpeechSummary,
};
const entries = [
  song("a", "Beta", "2026-10-02T10:00:00Z"),
  song("b", "Alpha", "2026-10-01T10:00:00Z"),
  speech,
];
const titles = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell")[1]?.textContent ?? "");

describe("CreationsTable", () => {
  it("shows each creation with its type, a link to it and its details", () => {
    render(<CreationsTable entries={entries} />);
    const link = screen.getByRole("link", { name: "আপনি কেমন আছেন?" });
    expect(link).toHaveAttribute("href", "/text-to-speech/creations/s1");
    expect(screen.getByText("বাংলা · Female, Aditi")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Beta" })).toHaveAttribute("href", "/music/songs/a");
  });

  it("keeps the order it was given until a header is clicked, then sorts by that column", async () => {
    render(<CreationsTable entries={entries} />);
    expect(titles()[0]).toContain("Beta");
    await userEvent.click(screen.getByRole("button", { name: /Made/ }));
    expect(titles()[0]).toContain("Alpha"); // oldest first
    await userEvent.click(screen.getByRole("button", { name: /Made/ }));
    expect(titles()[0]).toContain("আপনি");
  });
});
