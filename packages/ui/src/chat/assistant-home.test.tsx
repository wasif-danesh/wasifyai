import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, ImagesApi } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModelChoicesProvider, useChoicesChanged } from "../models";
import { AssistantHome, greeting } from "./AssistantHome";
// @vitest-environment jsdom
import { moreOptions } from "./options-testing";
import { conversationsChanged, useConversations } from "./use-conversations";

const runs = { startRun: vi.fn(async () => {}), watchRun: vi.fn(async () => {}) };
const images = {} as ImagesApi;

function fakeAssistant(over: Partial<AssistantApi> = {}): AssistantApi {
  return {
    options: vi.fn(async () => ({ thinking: false })),
    searchStatus: vi.fn(async () => {
      throw new Error("unused");
    }),
    updateSearch: vi.fn(async () => {
      throw new Error("unused");
    }),
    setHead: vi.fn(async () => {}),
    attach: vi.fn(async () => {
      throw new Error("unused");
    }),
    unattach: vi.fn(async () => {}),
    list: vi.fn(async () => [{ id: "c1", title: "Fox poem", created_at: "", updated_at: "" }]),
    get: vi.fn(async (id: string) => ({
      id,
      title: "Fox poem",
      created_at: "",
      updated_at: "",
      messages: [],
    })),
    rename: vi.fn(async (id: string, title: string) => ({
      id,
      title,
      created_at: "",
      updated_at: "",
    })),
    remove: vi.fn(async () => {}),
    ...over,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("greeting", () => {
  it("follows the hour", () => {
    expect(greeting(3)).toBe("Good night");
    expect(greeting(9)).toBe("Good morning");
    expect(greeting(14)).toBe("Good afternoon");
    expect(greeting(20)).toBe("Good evening");
  });
});

describe("AssistantHome", () => {
  it.each([true, false])(
    "offers the Thinking switch as the engine says the model can (%s)",
    async (can) => {
      render(
        <AssistantHome
          runs={runs}
          assistant={fakeAssistant({ options: vi.fn(async () => ({ thinking: can })) })}
          images={images}
          conversationId={null}
          onAdopt={() => {}}
          onNewChat={() => {}}
        />,
      );
      await screen.findByRole("heading", { level: 1 });
      // Thinking is in the box's "+" menu (ADR-0093 U9)
      await waitFor(async () =>
        expect((await moreOptions()).some((t) => t.startsWith("Thinking"))).toBe(can),
      );
    },
  );

  it("asks again what the box can do when another model is chosen", async () => {
    let can = false;
    const options = vi.fn(async () => ({ thinking: can }));
    function Choose() {
      const changed = useChoicesChanged();
      return (
        <button type="button" onClick={changed}>
          model chosen
        </button>
      );
    }
    const user = userEvent.setup();
    render(
      <ModelChoicesProvider source={() => null}>
        <Choose />
        <AssistantHome
          runs={runs}
          assistant={fakeAssistant({ options })}
          images={images}
          conversationId={null}
          onAdopt={() => {}}
          onNewChat={() => {}}
        />
      </ModelChoicesProvider>,
    );
    await screen.findByRole("heading", { level: 1 });
    expect((await moreOptions()).some((t) => t.startsWith("Thinking"))).toBe(false);
    can = true; // the model the person chose can think
    await user.click(screen.getByRole("button", { name: "model chosen" }));
    await waitFor(async () =>
      expect((await moreOptions()).some((t) => t.startsWith("Thinking"))).toBe(true),
    );
    expect(options).toHaveBeenCalledTimes(2);
  });

  it("greets a new chat and offers examples, with no title bar", async () => {
    render(
      <AssistantHome
        runs={runs}
        assistant={fakeAssistant()}
        images={images}
        conversationId={null}
        onAdopt={() => {}}
        onNewChat={() => {}}
      />,
    );
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(/good|hello/i);
    expect(screen.getByRole("button", { name: /draw a lighthouse/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /rename this chat/i })).toBeNull();
  });

  it("shows a saved chat's title and renames it in the app's own box", async () => {
    let stored = "Fox poem"; // the engine keeps the name: the list reads it back
    const assistant = fakeAssistant({
      list: vi.fn(async () => [{ id: "c1", title: stored, created_at: "", updated_at: "" }]),
      rename: vi.fn(async (id: string, title: string) => {
        stored = title;
        return { id, title, created_at: "", updated_at: "" };
      }),
    });
    const changed = vi.fn();
    window.addEventListener("wasifyai:conversations-changed", changed);
    const user = userEvent.setup();
    render(
      <AssistantHome
        runs={runs}
        assistant={assistant}
        images={images}
        conversationId="c1"
        onAdopt={() => {}}
        onNewChat={() => {}}
      />,
    );
    expect(await screen.findByText("Fox poem")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /rename this chat/i }));
    const box = screen.getByRole("dialog", { name: "Rename this chat" });
    const name = within(box).getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Renamed");
    await user.click(within(box).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(assistant.rename).toHaveBeenCalledWith("c1", "Renamed"));
    expect(await screen.findByText("Renamed")).toBeInTheDocument();
    expect(changed).toHaveBeenCalled();
    window.removeEventListener("wasifyai:conversations-changed", changed);
  });

  it("deletes the chat after asking, then goes to a new one", async () => {
    const assistant = fakeAssistant();
    const onNewChat = vi.fn();
    const user = userEvent.setup();
    render(
      <AssistantHome
        runs={runs}
        assistant={assistant}
        images={images}
        conversationId="c1"
        onAdopt={() => {}}
        onNewChat={onNewChat}
      />,
    );
    const del = await screen.findByRole("button", { name: /delete this chat/i });
    await user.click(del);
    await user.click(
      within(screen.getByRole("dialog", { name: "Delete this chat?" })).getByRole("button", {
        name: "Cancel",
      }),
    );
    expect(assistant.remove).not.toHaveBeenCalled(); // asked, and the answer was no
    await user.click(del);
    await user.click(
      within(screen.getByRole("dialog", { name: "Delete this chat?" })).getByRole("button", {
        name: "Delete",
      }),
    );
    await waitFor(() => expect(assistant.remove).toHaveBeenCalledWith("c1"));
    expect(onNewChat).toHaveBeenCalled();
  });
});

describe("useConversations", () => {
  it("reads the list, and again whenever a screen says a conversation changed", async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce([{ id: "a", title: "One", created_at: "", updated_at: "" }])
      .mockResolvedValue([
        { id: "b", title: "Two", created_at: "", updated_at: "" },
        { id: "a", title: "One", created_at: "", updated_at: "" },
      ]);
    const api = { list };
    const { result } = renderHook(() => useConversations(api, 5));
    await waitFor(() => expect(result.current.map((c) => c.id)).toEqual(["a"]));
    expect(list).toHaveBeenCalledWith(5);
    act(() => conversationsChanged());
    await waitFor(() => expect(result.current.map((c) => c.id)).toEqual(["b", "a"]));
  });
});
