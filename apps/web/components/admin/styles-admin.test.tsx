// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const ANIME = {
  id: "s1",
  title: "Flux klein 4b anime Koni",
  source: { kind: "hub", repo: "Sawata97/flux2_4b_koni_animestyle" },
  sha256: "x",
  size: 184832664,
  model: "FLUX.2 klein 4B",
  fit: "fits",
  made_for_base: false,
  rank: 64,
  unused_parts: 0,
  trigger: "anime_style",
  added_at: 1,
  selectable: true,
}; // fmt: skip

let rows = [ANIME];
const adminStyles = {
  list: vi.fn(async () => ({ styles: rows, found: [], max: 8 })),
  remove: vi.fn(async (id: string) => {
    rows = rows.filter((r) => r.id !== id);
  }),
  hubFiles: vi.fn(async () => ({
    repo: "a/b",
    commit: null,
    gated: false,
    files: [],
    refused: [],
    made_for_base: null,
    trigger: null,
    stale: false,
  })),
}; // fmt: skip
vi.mock("@/lib/library", () => ({ adminStyles }));

describe("Admin > Styles", () => {
  it("lists the service's styles with what each was made for and its word", async () => {
    const { StylesAdmin } = await import("./StylesAdmin");
    render(<StylesAdmin />);
    expect(await screen.findByText("Flux klein 4b anime Koni")).toBeInTheDocument();
    expect(screen.getByText("Made for FLUX.2 klein 4B · 185 MB")).toBeInTheDocument();
    expect(
      screen.getByText(/From Sawata97\/flux2_4b_koni_animestyle · word: anime_style/),
    ).toBeInTheDocument();
  });

  it("deletes only after a yes", async () => {
    const { StylesAdmin } = await import("./StylesAdmin");
    render(<StylesAdmin />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(adminStyles.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getAllByRole("button", { name: "Delete" }).at(-1) as HTMLElement);
    await waitFor(() => expect(adminStyles.remove).toHaveBeenCalledWith("s1"));
    expect(await screen.findByText(/No styles yet/)).toBeInTheDocument();
  });

  it("adds from Hugging Face through the same dialog as the desktop", async () => {
    const { StylesAdmin } = await import("./StylesAdmin");
    render(<StylesAdmin />);
    await userEvent.click(screen.getByRole("button", { name: "Add a style from Hugging Face" }));
    await userEvent.type(screen.getByLabelText("Name or address"), "a/b");
    await userEvent.click(screen.getByRole("button", { name: "Look" }));
    await waitFor(() => expect(adminStyles.hubFiles).toHaveBeenCalledWith("a/b"));
  });
});
