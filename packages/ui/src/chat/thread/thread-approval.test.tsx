// @vitest-environment jsdom
// The card that waits for the person (ADR-0071, stage CU2) on the new thread: it comes back after a reload, a click goes to the
// engine, the turn goes on in the same message, and moving on closes it.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, Conversation, ImagesApi, OnEvent, ParsedEvent } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { ChatScreenNext } from "../ChatScreenNext";

const ev = (event: string, seq: number, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r9", seq, ...data } }) as unknown as ParsedEvent;

const images = { get: async () => ({}) } as unknown as ImagesApi;

const waiting: Conversation = {
  id: "c1",
  title: "Foxes",
  created_at: "",
  updated_at: "",
  head_id: "t",
  messages: [
    {
      id: "u",
      seq: 1,
      role: "user",
      created_at: "",
      parent_id: null,
      parts: [{ type: "text", text: "draw a fox" }],
    },
    {
      id: "a",
      seq: 2,
      role: "assistant",
      created_at: "",
      parent_id: "u",
      parts: [
        { type: "text", text: "Let me draw it." },
        { type: "tool_call", id: "t1", name: "generate_image", arguments: { prompt: "a fox" } },
      ],
    },
    {
      id: "t",
      seq: 3,
      role: "tool",
      created_at: "",
      parent_id: "a",
      parts: [
        {
          type: "interrupt",
          kind: "confirm_action",
          status: "pending",
          tool_call_id: "t1",
          approval_id: "ap1",
          run_id: "r9",
          title: "Make a picture",
          summary: "Make a picture",
          params: { prompt: "a fox in <b>snow</b>" },
        },
      ],
    },
  ],
};

function api(): AssistantApi {
  return {
    options: async () => ({ thinking: false }),
    searchStatus: async () => {
      throw new Error("unused");
    },
    updateSearch: async () => {
      throw new Error("unused");
    },
    setHead: async () => {},
    attach: async () => {
      throw new Error("unused");
    },
    unattach: async () => {},
    list: async () => [],
    get: vi.fn(async () => waiting),
    rename: async () => {
      throw new Error("unused");
    },
    remove: async () => {},
  };
}

function runs(resumed: object[] = [], started: object[] = []) {
  return {
    startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
      started.push(input);
      on(ev("token", 1, { text: "ok" }));
      on(ev("done", 2, { outputs: { status: "done", conversation_id: "c1", title: "Foxes" } }));
    }),
    watchRun: vi.fn(async () => {}),
    cancelRun: vi.fn(async () => {}),
    resumeRun: vi.fn(async (_id: string, value: object, _s: AbortSignal, on: OnEvent) => {
      resumed.push(value);
      on(
        ev("tool_result", 5, {
          id: "t1",
          name: "generate_image",
          status: "ok",
          output: { image_id: "i1" },
        }),
      );
      on(ev("token", 6, { text: "Here is your fox." }));
      on(ev("done", 7, { outputs: { status: "done", conversation_id: "c1", title: "Foxes" } }));
    }),
  };
}

describe("the confirm card", () => {
  it("comes back after a reload with what will be made, as plain text", async () => {
    render(<ChatScreenNext runs={runs()} assistant={api()} images={images} conversationId="c1" />);
    const card = await screen.findByRole("region", { name: "Make a picture" });
    expect(card).toHaveTextContent("a fox in <b>snow</b>"); // shown as text, never as markup
    expect(card.querySelector("b")).toBeNull();
    expect(screen.getByRole("button", { name: "Go ahead" })).toBeEnabled();
  });

  it("a click on Go ahead answers the run and the turn goes on in the same message", async () => {
    const resumed: object[] = [];
    const user = userEvent.setup();
    render(
      <ChatScreenNext runs={runs(resumed)} assistant={api()} images={images} conversationId="c1" />,
    );
    await user.click(await screen.findByRole("button", { name: "Go ahead" }));
    await waitFor(() => expect(resumed).toEqual([{ approved: true }]));
    expect(await screen.findByText("Here is your fox.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Go ahead" })).toBeNull();
    expect(screen.getByText("Let me draw it.")).toBeInTheDocument(); // one message, not two
  });

  it("Not now says no, and nothing is shown as approved", async () => {
    const resumed: object[] = [];
    const user = userEvent.setup();
    render(
      <ChatScreenNext runs={runs(resumed)} assistant={api()} images={images} conversationId="c1" />,
    );
    await user.click(await screen.findByRole("button", { name: "Not now" }));
    await waitFor(() => expect(resumed).toEqual([{ approved: false }]));
  });

  it("typing a new message while the card waits closes the card first, then sends", async () => {
    const resumed: object[] = [];
    const started: object[] = [];
    const user = userEvent.setup();
    render(
      <ChatScreenNext
        runs={runs(resumed, started)}
        assistant={api()}
        images={images}
        conversationId="c1"
      />,
    );
    await screen.findByRole("button", { name: "Go ahead" });
    await user.type(screen.getByRole("textbox", { name: "Message" }), "never mind{Enter}");
    await waitFor(() => expect(started).toHaveLength(1));
    expect(resumed).toEqual([{ approved: false, expired: true }]);
    expect(started[0]).toMatchObject({ text: "never mind", parent_message_id: "a" });
  });
});
