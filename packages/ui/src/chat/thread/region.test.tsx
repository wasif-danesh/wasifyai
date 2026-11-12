// @vitest-environment jsdom
// Pointing at a picture in the chat (docs/chat-does-everything-plan.md, CE6): the card of a change to part of a picture
// draws the area on the picture, and the person can draw another before Run; "Change an area" under a picture asks the
// chat to change only the box drawn.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AssistantApi, Conversation, ImagesApi, OnEvent, ParsedEvent } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { ChatScreen } from "../ChatScreen";

const ev = (event: string, seq: number, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r9", seq, ...data } }) as unknown as ParsedEvent;

const images = {
  get: async () => ({
    image_url: "http://x/room.png",
    prompt: "a living room",
    width: 100,
    height: 100,
  }),
} as unknown as ImagesApi;

const sky = { left: 0, top: 0, width: 1, height: 0.4 };

const waiting: Conversation = {
  id: "c1",
  title: "Room",
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
      parts: [{ type: "text", text: "a green sofa" }],
    },
    {
      id: "a",
      seq: 2,
      role: "assistant",
      created_at: "",
      parent_id: "u",
      parts: [
        {
          type: "tool_call",
          id: "t1",
          name: "propose_action",
          arguments: {
            action_id: "image.inpaint",
            params: { image_id: "img-1", prompt: "a green sofa", area: "the sofa" },
          },
        },
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
          title: "Change part of a picture",
          summary: "Change part of a picture",
          action_id: "image.inpaint",
          effect: "make",
          params: { image_id: "img-1", prompt: "a green sofa", area: "the sofa" },
          fields: [
            {
              name: "prompt",
              label: "prompt",
              kind: "text",
              required: true,
              value: "a green sofa",
            },
          ],
          region: sky,
        } as never,
      ],
    },
  ],
};

function api(): AssistantApi {
  const no = async () => {
    throw new Error("unused");
  };
  return {
    options: async () => ({ thinking: false }),
    searchStatus: no,
    updateSearch: no,
    setHead: async () => {},
    attach: no,
    unattach: async () => {},
    list: async () => [],
    get: vi.fn(async () => waiting),
    rename: no,
    remove: async () => {},
  } as unknown as AssistantApi;
}

function runs(resumed: object[] = [], started: object[] = []) {
  return {
    startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
      started.push(input);
      on(ev("done", 2, { outputs: { status: "done", conversation_id: "c1", title: "Room" } }));
    }),
    watchRun: vi.fn(async () => {}),
    cancelRun: vi.fn(async () => {}),
    resumeRun: vi.fn(async (_id: string, value: object, _s: AbortSignal, on: OnEvent) => {
      resumed.push(value);
      on(ev("done", 7, { outputs: { status: "done", conversation_id: "c1", title: "Room" } }));
    }),
  };
}

function frameOf(img: HTMLElement): HTMLElement {
  const frame = img.parentElement as HTMLElement;
  frame.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 }) as DOMRect;
  return frame;
}

describe("pointing at a picture", () => {
  it("draws the area the chat found on the card, and sends another the person drew", async () => {
    const resumed: object[] = [];
    const user = userEvent.setup();
    render(
      <ChatScreen runs={runs(resumed)} assistant={api()} images={images} conversationId="c1" />,
    );
    const img = await screen.findByRole("img", { name: "a living room" });
    expect(screen.getByTestId("region-box")).toHaveStyle({ width: "100%", height: "40%" });
    expect(
      screen.getByText(/The area to change: from 0% across and 0% down, 100% wide and 40% tall/),
    ).toBeInTheDocument();
    const frame = frameOf(img);
    await user.pointer([
      { keys: "[MouseLeft>]", target: frame, coords: { clientX: 20, clientY: 50 } },
      { target: frame, coords: { clientX: 60, clientY: 90 } },
      { keys: "[/MouseLeft]", target: frame, coords: { clientX: 60, clientY: 90 } },
    ]);
    expect(
      screen.getByText(/from 20% across and 50% down, 40% wide and 40% tall/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Make it" }));
    await waitFor(() => expect(resumed).toHaveLength(1));
    expect(resumed[0]).toMatchObject({
      approved: true,
      params: { prompt: "a green sofa", region: { left: 0.2, top: 0.5, width: 0.4, height: 0.4 } },
    });
  });

  it("asks the chat to change only a box drawn on a picture it made", async () => {
    const started: object[] = [];
    const run = {
      ...runs([], started),
      startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
        started.push(input);
        on(
          ev("tool_call", 1, {
            id: "t1",
            name: "propose_action",
            arguments: { action_id: "image.generate", params: {} },
          }),
        );
        on(
          ev("tool_result", 2, {
            id: "t1",
            name: "propose_action",
            status: "ok",
            output: { action_id: "image.generate", image_id: "img-1" },
          }),
        );
        on(ev("done", 3, { outputs: { status: "done", conversation_id: "c1", title: "Room" } }));
      }),
    };
    const user = userEvent.setup();
    const assistant = {
      ...api(),
      get: vi.fn(async () => ({ ...waiting, messages: [] })),
    } as AssistantApi;
    render(<ChatScreen runs={run} assistant={assistant} images={images} />);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "draw a room{Enter}");
    await user.click(await screen.findByRole("button", { name: "Change an area" }));
    const imgs = await screen.findAllByRole("img", { name: "a living room" });
    const frame = frameOf(imgs[imgs.length - 1] as HTMLElement);
    await user.pointer([
      { keys: "[MouseLeft>]", target: frame, coords: { clientX: 10, clientY: 10 } },
      { target: frame, coords: { clientX: 30, clientY: 50 } },
      { keys: "[/MouseLeft]", target: frame, coords: { clientX: 30, clientY: 50 } },
    ]);
    await user.type(screen.getByLabelText("What to put there"), "a green armchair");
    await user.click(screen.getByRole("button", { name: "Change it" }));
    await waitFor(() => expect(started).toHaveLength(2));
    expect(started[1]).toMatchObject({
      text: "Change only this area of picture img-1 (region left 0.1, top 0.1, width 0.2, height 0.4) into: a green armchair",
    });
  });
});
