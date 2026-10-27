// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Shield } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { SideMenu } from "./SideMenu";
import { type ItemResolver, MENU_ENTRIES, MENU_GROUPS, entryOf, placeOf } from "./menu";

const none: ItemResolver = () => undefined;

describe("the menu definition", () => {
  it("has the items in groups, each id once, and eleven entries over them", () => {
    expect(MENU_GROUPS.map((g) => g.label)).toEqual([
      "Notebook",
      "Images",
      "Video",
      "Voice",
      "Music",
    ]);
    const ids = MENU_GROUPS.flatMap((g) => g.items.map((i) => i.id));
    expect(new Set(ids).size).toBe(ids.length); // every id is unique
    expect(MENU_ENTRIES.map((e) => e.label)).toEqual([
      "Chat",
      "Notebooks",
      "Images",
      "Video",
      "Motion graphics",
      "Speech",
      "Studio",
      "Music",
      "3D model",
      "Library",
      "Train models",
      "Model hub",
    ]);
    // every entry's items are real items, and the eight voice tools are split between Speech and Studio
    const items = (id: string) => MENU_ENTRIES.find((e) => e.id === id)?.items.map((i) => i.label);
    expect(items("images")).toEqual(["Create", "Edit", "Inpaint", "Reference", "Your images"]);
    expect(items("speech")).toEqual([
      "Text to speech",
      "Speech to text",
      "Voices",
      "Change a voice",
      "Edit speech",
    ]);
    expect(items("studio")).toEqual(["Dub a recording", "Audiobook", "Lip sync"]);
    expect(entryOf("voice.dub")?.id).toBe("studio");
    expect(entryOf("notebook.create")).toBeUndefined(); // reached from the Notebooks screen, not the menu
  });

  it("says where a person is from what is current, with tabs when the entry has several tools", () => {
    const at =
      (current: string): ItemResolver =>
      (id) => ({ href: `/${id}`, current: id === current });
    const images = placeOf(at("images.edit"));
    expect(images?.entry.id).toBe("images");
    expect(images?.item?.id).toBe("images.edit");
    expect(images?.tabs.map((t) => t.item.label)).toEqual([
      "Create",
      "Edit",
      "Inpaint",
      "Reference",
      "Your images",
    ]);
    const train = placeOf(at("train"));
    expect(train?.entry.label).toBe("Train models");
    expect(train?.tabs).toEqual([]); // one tool: no tabs
    expect(placeOf(() => undefined)).toBeNull();
    // a tool the app does not serve is not a tab
    const some: ItemResolver = (id) =>
      id === "voice.speak"
        ? { href: "/speak", current: true }
        : id === "voice.transcribe"
          ? { href: "/t" }
          : undefined;
    expect(placeOf(some)?.tabs.map((t) => t.item.id)).toEqual(["voice.speak", "voice.transcribe"]);
  });
});

describe("SideMenu", () => {
  it("shows what an app does not serve as disabled and marked Soon", () => {
    render(<SideMenu resolve={none} />);
    const chat = screen.getByRole("button", { name: /^Chat/ });
    expect(chat).toBeDisabled();
    expect(within(chat).getByText("Soon")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Video/ })).toBeDisabled();
  });

  it("is one click to a tool: an entry opens its first tool, or stays on the open one", async () => {
    const user = userEvent.setup();
    const go = vi.fn();
    const resolve: ItemResolver = (id) =>
      id.startsWith("video.") || id === "chat"
        ? { current: id === "video.extend", onSelect: () => go(id) }
        : undefined;
    render(<SideMenu resolve={resolve} />);
    const video = screen.getByRole("button", { name: "Video" });
    expect(video).toHaveAttribute("aria-current", "page");
    await user.click(video);
    expect(go).toHaveBeenCalledWith("video.extend"); // the open tool
    await user.click(screen.getByRole("button", { name: "Chat" }));
    expect(go).toHaveBeenCalledWith("chat");
    // no group to open, no second level
    expect(screen.queryByRole("button", { name: /Your videos/ })).toBeNull();
    expect(screen.queryByRole("button", { expanded: true })).toBeNull();
  });

  it("links an entry where the app has addresses and marks the page", () => {
    const resolve: ItemResolver = (id) =>
      id === "video.library"
        ? { href: "/video/library", current: true }
        : id === "video.create"
          ? { href: "/video" }
          : undefined;
    render(<SideMenu resolve={resolve} />);
    const here = screen.getByRole("link", { name: "Video" });
    expect(here).toHaveAttribute("href", "/video/library"); // stays on the open tool
    expect(here).toHaveAttribute("aria-current", "page");
  });

  it("leaves out an entry the app hides on purpose", () => {
    const resolve: ItemResolver = (id) => (id === "models" ? { hidden: true } : undefined);
    render(<SideMenu resolve={resolve} />);
    expect(screen.queryByText("Model hub")).toBeNull();
    expect(screen.getByRole("button", { name: /Train models/ })).toBeInTheDocument();
  });

  it("shows the extra items, the recents and the footer it is given", () => {
    const select = vi.fn();
    render(
      <SideMenu
        resolve={none}
        recents={{ items: [{ id: "a", title: "Fox poem", current: true, onSelect: select }] }}
        extra={[{ id: "admin", label: "Admin", icon: Shield, href: "/admin", current: false }]}
        footer={<span>Ada</span>}
      />,
    );
    expect(screen.getByRole("link", { name: /Admin/ })).toHaveAttribute("href", "/admin");
    expect(screen.getByRole("button", { name: "Fox poem" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("Ada")).toBeInTheDocument();
  });
});
