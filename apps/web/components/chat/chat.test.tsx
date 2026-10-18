// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatHome } from "./ChatHome";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  usePathname: () => "/",
}));

const fetchMock = vi.fn();
beforeEach(() => {
  sessionStorage.clear();
  push.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const CHAT = "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80";

function frames(list: [string, object][]): string {
  return list
    .map(
      ([event, data], i) =>
        `id: ${i + 1}\nevent: ${event}\ndata: ${JSON.stringify({ run_id: "r1", thread_id: "t", seq: i + 1, ts: "", ...data })}\n\n`,
    )
    .join("");
}

describe("ChatHome (the web app's mount of the shared home screen)", () => {
  it("answers through the BFF and gives the new chat its address without a reload", async () => {
    const replace = vi.spyOn(window.history, "replaceState");
    fetchMock.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/products/wasifyai-assistant/runs")) {
        return new Response(
          frames([
            ["node", { node: "agent", status: "started", label: "Thinking" }],
            ["token", { node: "agent", text: "A fox is a small wild dog." }],
            ["done", { outputs: { status: "done", conversation_id: CHAT, title: "Foxes" } }],
          ]),
          { headers: { "content-type": "text/event-stream" } },
        );
      }
      return Response.json({ conversations: [] });
    });
    const user = userEvent.setup();
    render(<ChatHome conversationId={null} />);
    await user.type(await screen.findByRole("textbox"), "What is a fox?");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("A fox is a small wild dog.")).toBeInTheDocument();
    const start = fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/runs"));
    expect(start?.[0]).toBe("/api/products/wasifyai-assistant/runs");
    await waitFor(() => expect(replace).toHaveBeenCalledWith(null, "", `/chat/${CHAT}`));
  });

  it("opens a saved chat with its title, and goes home when it is deleted", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      if (path.includes(`/conversations/${CHAT}`)) {
        return Response.json({
          id: CHAT,
          title: "Foxes",
          created_at: "",
          updated_at: "",
          messages: [
            {
              id: "m1",
              seq: 1,
              role: "user",
              created_at: "",
              parts: [{ type: "text", text: "Hi" }],
            },
          ],
        });
      }
      return Response.json({
        conversations: [{ id: CHAT, title: "Foxes", created_at: "", updated_at: "" }],
      });
    });
    const user = userEvent.setup();
    render(<ChatHome conversationId={CHAT} />);
    expect(await screen.findByText("Foxes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /delete this chat/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
  });
});
