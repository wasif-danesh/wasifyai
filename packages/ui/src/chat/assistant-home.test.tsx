// @vitest-environment jsdom
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, ImagesApi } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantHome, greeting } from "./AssistantHome";
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
      await waitFor(() =>
        expect(screen.queryAllByRole("button", { name: /^Thinking/ })).toHaveLength(can ? 1 : 0),
      );
    },
  );

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

  it("shows a saved chat's title and renames it", async () => {
    const assistant = fakeAssistant();
    vi.spyOn(window, "prompt").mockReturnValue("Renamed");
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
    expect(assistant.rename).toHaveBeenCalledWith("c1", "Renamed");
    expect(await screen.findByText("Renamed")).toBeInTheDocument();
    expect(changed).toHaveBeenCalled();
    window.removeEventListener("wasifyai:conversations-changed", changed);
  });

  it("deletes the chat after asking, then goes to a new one", async () => {
    const assistant = fakeAssistant();
    const onNewChat = vi.fn();
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
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
    expect(assistant.remove).not.toHaveBeenCalled(); // asked, and the answer was no
    await user.click(del);
    expect(confirm).toHaveBeenCalledTimes(2);
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
