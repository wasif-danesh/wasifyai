// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Shield } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { SideMenu } from "./SideMenu";
import { type ItemResolver, MENU_GROUPS, placesOf, titleOf } from "./menu";

const none: ItemResolver = () => undefined;

describe("the menu definition", () => {
  it("has the groups in order, each with its items", () => {
    expect(MENU_GROUPS.map((g) => g.label)).toEqual([
      "Notebook",
      "Images",
      "Video",
      "Voice",
      "Music",
    ]);
    const items = (id: string) => MENU_GROUPS.find((g) => g.id === id)?.items.map((i) => i.label);
    expect(items("notebook")).toEqual(["Create", "View notebooks"]);
    expect(items("video")).toEqual(["Create", "Animate an image", "Extend video", "Your videos"]);
    expect(items("music")).toEqual(["Create", "Your music", "Lyrics", "Split into parts"]);
    expect(items("voice")).toHaveLength(8);
    const ids = MENU_GROUPS.flatMap((g) => g.items.map((i) => i.id));
    expect(new Set(ids).size).toBe(ids.length); // every id is unique
  });
});

describe("SideMenu", () => {
  it("shows what an app does not serve as disabled and marked Soon", async () => {
    const user = userEvent.setup();
    render(<SideMenu resolve={none} />);
    expect(screen.getByRole("button", { name: /new chat/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /^Video/ }));
    const create = screen.getByRole("button", { name: /Create/ });
    expect(create).toBeDisabled();
    expect(within(create).getByText("Soon")).toBeInTheDocument();
  });

  it("opens one group at a time", async () => {
    const user = userEvent.setup();
    render(<SideMenu resolve={none} />);
    await user.click(screen.getByRole("button", { name: /^Images/ }));
    expect(screen.getByRole("button", { name: /Your images/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Music/ }));
    expect(screen.queryByRole("button", { name: /Your images/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Your music/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Music/ }));
    expect(screen.queryByRole("button", { name: /Your music/ })).toBeNull();
  });

  it("keeps the group of the current page open and marks the page", () => {
    const resolve: ItemResolver = (id) =>
      id === "video.library" ? { href: "/video/library", current: true } : undefined;
    render(<SideMenu resolve={resolve} />);
    const here = screen.getByRole("link", { name: /Your videos/ });
    expect(here).toHaveAttribute("href", "/video/library");
    expect(here).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Video" })).toHaveAttribute("aria-expanded", "true");
  });

  it("lets a person open another group while on a page, and follows them to the next page", async () => {
    const user = userEvent.setup();
    let page = "video.library";
    const resolve: ItemResolver = (id) =>
      id === page ? { href: `/${id}`, current: true } : id.startsWith("music.") ? {} : undefined;
    const { rerender } = render(<SideMenu resolve={resolve} />);
    expect(screen.getByRole("link", { name: /Your videos/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Music/ }));
    expect(screen.getByRole("button", { name: /Your music/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Your videos/ })).toBeNull();
    // opening a page of another group opens that group again
    page = "images.library";
    rerender(<SideMenu resolve={resolve} />);
    expect(screen.getByRole("link", { name: /Your images/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Your music/ })).toBeNull();
    // and the group of the current page can be closed
    await user.click(screen.getByRole("button", { name: /^Images/ }));
    expect(screen.queryByRole("link", { name: /Your images/ })).toBeNull();
  });

  it("runs what an item does and leaves hidden items out", async () => {
    const onSelect = vi.fn();
    const resolve: ItemResolver = (id) =>
      id === "chat"
        ? { onSelect, current: true }
        : id === "models"
          ? { hidden: true }
          : id === "library"
            ? { href: "/creations" }
            : undefined;
    const user = userEvent.setup();
    render(<SideMenu resolve={resolve} />);
    const chat = screen.getByRole("button", { name: /new chat/i });
    expect(chat).toHaveAttribute("aria-current", "page");
    await user.click(chat);
    expect(onSelect).toHaveBeenCalledOnce();
    expect(screen.queryByText("Model hub")).toBeNull();
    expect(screen.getByRole("link", { name: /Library/ })).toHaveAttribute("href", "/creations");
    expect(screen.getByRole("button", { name: /Train/ })).toBeDisabled();
  });

  it("draws links with the app's own component", () => {
    const Custom = ({ href, children }: { href: string; children: React.ReactNode }) => (
      <a href={href} data-custom="yes">
        {children}
      </a>
    );
    render(
      <SideMenu resolve={(id) => (id === "library" ? { href: "/x" } : undefined)} link={Custom} />,
    );
    expect(screen.getByRole("link", { name: /Library/ })).toHaveAttribute("data-custom", "yes");
  });

  it("makes the brand a link when it has somewhere to go", () => {
    const { rerender } = render(<SideMenu resolve={none} />);
    expect(screen.queryByRole("link", { name: /home/i })).toBeNull();
    rerender(<SideMenu resolve={none} brandHref="/" />);
    expect(screen.getByRole("link", { name: "Wasify AI, home" })).toHaveAttribute("href", "/");
  });

  it("shows recents, extra items and the footer only when given", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<SideMenu resolve={none} />);
    expect(screen.queryByText("Recents")).toBeNull();

    const open = vi.fn();
    rerender(
      <SideMenu
        resolve={none}
        recents={{ items: [{ id: "c1", title: "Fox poem", current: true, onSelect: open }] }}
        extra={[{ id: "admin", label: "Admin", icon: Shield, href: "/admin" }]}
        footer={<p>Signed in as Sam</p>}
      />,
    );
    const chat = screen.getByRole("button", { name: "Fox poem" });
    expect(chat).toHaveAttribute("aria-current", "page");
    await user.click(chat);
    expect(open).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /Admin/ })).toHaveAttribute("href", "/admin");
    expect(screen.getByText("Signed in as Sam")).toBeInTheDocument();

    rerender(<SideMenu resolve={none} recents={{ items: [] }} />);
    expect(screen.getByText("No chats yet")).toBeInTheDocument();
  });
});

describe("the bar's words for the menu", () => {
  it("names the group a person is in, and lists every served tool for the search", () => {
    const at =
      (current: string): ItemResolver =>
      (id) =>
        id === "models" ? { hidden: true } : { href: `/${id}`, current: id === current };
    expect(titleOf(at("images.edit"))).toBe("Images");
    expect(titleOf(at("voice.dub"))).toBe("Voice");
    expect(titleOf(at("train"))).toBe("Train models");
    expect(titleOf(at("chat"))).toBe("Chat");
    expect(titleOf(() => undefined)).toBeNull();
    const places = placesOf(at("chat"));
    expect(places.map((p) => p.label)).toContain("Images: Edit");
    expect(places.map((p) => p.label)).toContain("Motion graphics");
    expect(places.some((p) => p.id === "models")).toBe(false); // hidden on purpose: not offered
  });
});
