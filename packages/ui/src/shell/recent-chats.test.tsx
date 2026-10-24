// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type RecentChat, RecentChats } from "./RecentChats";

afterEach(cleanup);

function chat(over: Partial<RecentChat> = {}): RecentChat {
  return {
    id: "c1",
    title: "Fox poem",
    onSelect: vi.fn(),
    rename: vi.fn(async () => {}),
    remove: vi.fn(async () => {}),
    ...over,
  };
}

describe("the recent chats", () => {
  it("opens a chat on a click and keeps the options out of the way", async () => {
    const c = chat();
    render(<RecentChats recents={{ items: [c] }} />);
    await userEvent.click(screen.getByRole("button", { name: "Fox poem" }));
    expect(c.onSelect).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("offers Rename and Delete from the options button", async () => {
    render(<RecentChats recents={{ items: [chat()] }} />);
    await userEvent.click(screen.getByRole("button", { name: "Options for Fox poem" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Rename" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Delete" })).toBeInTheDocument();
  });

  it("opens the same menu with a right click, and closes it with Escape", async () => {
    render(<RecentChats recents={{ items: [chat()] }} />);
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.contextMenu(screen.getByRole("button", { name: "Fox poem" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("renames with the name box", async () => {
    const c = chat();
    render(<RecentChats recents={{ items: [c] }} />);
    await userEvent.click(screen.getByRole("button", { name: "Options for Fox poem" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const box = screen.getByRole("dialog", { name: "Rename this chat" });
    const name = within(box).getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Winter fox");
    await userEvent.click(within(box).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(c.rename).toHaveBeenCalledWith("Winter fox"));
  });

  it("deletes only after the question is answered yes", async () => {
    const c = chat();
    render(<RecentChats recents={{ items: [c] }} />);
    await userEvent.click(screen.getByRole("button", { name: "Options for Fox poem" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    await userEvent.click(
      within(screen.getByRole("dialog", { name: "Delete this chat?" })).getByRole("button", {
        name: "Cancel",
      }),
    );
    expect(c.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Options for Fox poem" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    await userEvent.click(
      within(screen.getByRole("dialog", { name: "Delete this chat?" })).getByRole("button", {
        name: "Delete",
      }),
    );
    await waitFor(() => expect(c.remove).toHaveBeenCalledOnce());
  });

  it("says in words when it could not be done", async () => {
    const c = chat({
      remove: vi.fn(async () => {
        throw new Error("down");
      }),
    });
    render(<RecentChats recents={{ items: [c] }} />);
    await userEvent.click(screen.getByRole("button", { name: "Options for Fox poem" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    await userEvent.click(
      within(screen.getByRole("dialog", { name: "Delete this chat?" })).getByRole("button", {
        name: "Delete",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be deleted");
  });

  it("shows no options for a chat the app cannot change", () => {
    render(<RecentChats recents={{ items: [chat({ rename: undefined, remove: undefined })] }} />);
    expect(screen.queryByRole("button", { name: /Options for/ })).toBeNull();
  });
});
