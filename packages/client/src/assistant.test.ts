import { describe, expect, it } from "vitest";
import {
  type ChatAction,
  type ChatState,
  chatReducer,
  createAssistantApi,
  fromStored,
  initialChat,
} from "./assistant";
import type { ParsedEvent } from "./sse";

const ev = (event: string, data: Record<string, unknown> = {}): ChatAction => ({
  type: "event",
  event: { event, data: { run_id: "r1", seq: 1, ...data } } as unknown as ParsedEvent,
});

function run(actions: ChatAction[]): ChatState {
  return actions.reduce(chatReducer, initialChat);
}

describe("chatReducer", () => {
  it("shows the person's message and an answer that grows as it streams", () => {
    const s = run([
      { type: "submitted", text: "Hello", id: "u1" },
      ev("token", { text: "Hi " }),
      ev("token", { text: "there" }),
    ]);
    expect(s.phase).toBe("working");
    expect(s.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(s.messages[1]?.parts).toEqual([{ type: "text", text: "Hi there" }]);
    expect(s.messages[1]?.streaming).toBe(true);
  });

  it("finishes with the conversation and its title", () => {
    const s = run([
      { type: "submitted", text: "Hello", id: "u1" },
      ev("token", { text: "Hi" }),
      ev("done", { outputs: { status: "done", conversation_id: "c1", title: "Hello" } }),
    ]);
    expect(s.phase).toBe("idle");
    expect(s.conversationId).toBe("c1");
    expect(s.title).toBe("Hello");
    expect(s.messages[1]?.streaming).toBe(false);
  });

  it("puts a tool card between the words, with progress and then its result", () => {
    const s = run([
      { type: "submitted", text: "draw", id: "u1" },
      ev("token", { text: "Drawing. " }),
      ev("tool_call", { id: "t1", name: "generate_image", arguments: { prompt: "a fox" } }),
      ev("job_progress", { status: "running", progress: 0.4 }),
      ev("tool_result", {
        id: "t1",
        name: "generate_image",
        status: "ok",
        output: { image_id: "i1" },
      }),
      ev("token", { text: "Here it is." }),
    ]);
    const parts = s.messages[1]?.parts ?? [];
    expect(parts.map((p) => p.type)).toEqual(["text", "tool", "text"]);
    const tool = parts[1];
    expect(tool && tool.type === "tool" && tool.status).toBe("ok");
    expect(tool && tool.type === "tool" && tool.output).toEqual({ image_id: "i1" });
    expect(tool && tool.type === "tool" && tool.progress).toBe(0.4);
  });

  it("gives progress to the tool call it names, not to the last one running", () => {
    const s = run([
      { type: "submitted", text: "draw and search", id: "u1" },
      ev("tool_call", { id: "job", name: "generate_image", arguments: {} }),
      ev("tool_call", { id: "find", name: "search_creations", arguments: {} }),
      ev("job_progress", { tool_call_id: "job", status: "running", progress: 0.6 }),
    ]);
    const tools = (s.messages[1]?.parts ?? []).filter((p) => p.type === "tool");
    expect(tools.map((t) => t.type === "tool" && t.progress)).toEqual([0.6, undefined]);
  });

  it("keeps the model's thinking apart from its answer, in order", () => {
    const s = run([
      { type: "submitted", text: "hi", id: "u1" },
      ev("reasoning", { text: "The person " }),
      ev("reasoning", { text: "said hi." }),
      ev("token", { text: "Hello" }),
    ]);
    expect(s.messages[1]?.parts).toEqual([
      { type: "reasoning", text: "The person said hi." },
      { type: "text", text: "Hello" },
    ]);
  });

  it("shows stored thinking where it was, and a reload looks like the stream did", () => {
    const messages = fromStored([
      { id: "m1", seq: 1, role: "user", created_at: "", parts: [{ type: "text", text: "hi" }] },
      {
        id: "m2",
        seq: 2,
        role: "assistant",
        created_at: "",
        parts: [
          { type: "reasoning", text: "Hmm." },
          { type: "text", text: "Hello" },
        ],
      },
    ]);
    expect(messages[1]?.parts.map((p) => p.type)).toEqual(["reasoning", "text"]);
  });

  it("goes back to work on the same reply when the connection is picked up again", () => {
    const s = run([
      { type: "submitted", text: "hi", id: "u1" },
      ev("token", { text: "Par" }),
      { type: "failed", message: "We lost the connection.", code: "connection_lost" },
      { type: "resumed" },
      ev("token", { text: "tial" }),
    ]);
    expect(s.phase).toBe("working");
    expect(s.error).toBeNull();
    expect(s.messages).toHaveLength(2);
    expect(s.messages[1]).toMatchObject({ streaming: true, parts: [{ text: "Partial" }] });
  });

  it("keeps what was said and says what went wrong when the run fails", () => {
    const s = run([
      { type: "submitted", text: "hi", id: "u1" },
      ev("token", { text: "Par" }),
      ev("error", {
        code: "language_failed",
        message: "The model did not answer.",
        retryable: true,
      }),
    ]);
    expect(s.phase).toBe("error");
    expect(s.error).toEqual({
      code: "language_failed",
      message: "The model did not answer.",
      retryable: true,
    });
    expect(s.messages[1]?.parts).toEqual([{ type: "text", text: "Par" }]);
    expect(s.messages[1]?.streaming).toBe(false);
  });

  it("drops the empty answer when nothing came, and reports a refusal as such", () => {
    const refused = run([
      { type: "submitted", text: "hi", id: "u1" },
      ev("done", {
        outputs: { status: "refused", refusal: { code: "not_found", message: "Gone." } },
      }),
    ]);
    expect(refused.messages.map((m) => m.role)).toEqual(["user"]);
    expect(refused.error?.code).toBe("not_found");
    expect(refused.error?.retryable).toBe(false);

    const failed = run([
      { type: "submitted", text: "hi", id: "u1" },
      ev("error", { code: "no_language_model", message: "Choose one.", retryable: false }),
    ]);
    expect(failed.messages.map((m) => m.role)).toEqual(["user"]);
  });

  it("remembers the run and how far it got, for a reconnect", () => {
    const s = run([
      { type: "submitted", text: "hi", id: "u1" },
      ev("token", { text: "a", seq: 4 }),
      ev("token", { text: "b", seq: 5 }),
    ]);
    expect(s.runId).toBe("r1");
    expect(s.lastSeq).toBe(5);
  });
});

describe("fromStored", () => {
  it("folds a tool exchange into one assistant message, as the stream showed it", () => {
    const msgs = fromStored([
      {
        id: "1",
        seq: 1,
        role: "user",
        created_at: "",
        parts: [{ type: "text", text: "draw a fox" }],
      },
      {
        id: "2",
        seq: 2,
        role: "assistant",
        created_at: "",
        parts: [
          { type: "text", text: "Sure." },
          { type: "tool_call", id: "c1", name: "generate_image", arguments: { prompt: "a fox" } },
        ],
      },
      {
        id: "3",
        seq: 3,
        role: "tool",
        created_at: "",
        parts: [
          {
            type: "tool_result",
            id: "c1",
            name: "generate_image",
            status: "ok",
            output: { image_id: "i1" },
            text: "made",
          },
        ],
      },
      {
        id: "4",
        seq: 4,
        role: "assistant",
        created_at: "",
        parts: [{ type: "text", text: "Done." }],
      },
    ]);
    expect(msgs.map((m) => m.role)).toEqual(["user", "assistant"]);
    const parts = msgs[1]?.parts ?? [];
    expect(parts.map((p) => p.type)).toEqual(["text", "tool", "text"]);
    const tool = parts[1];
    expect(tool && tool.type === "tool" && tool.status).toBe("ok");
  });
});

describe("assistant api", () => {
  it("asks what the chat box can offer with the model in use", async () => {
    const calls: string[] = [];
    const api = createAssistantApi({
      async fetch(path) {
        calls.push(path);
        return new Response(JSON.stringify({ thinking: true }), { status: 200 });
      },
    });
    expect(await api.options()).toEqual({ thinking: true });
    expect(calls).toEqual(["/products/wasifyai-assistant/options"]);
  });

  it("reads and changes the web search settings, sending a key but never asking for one back", async () => {
    const calls: { path: string; init?: RequestInit }[] = [];
    const status = {
      provider: "duckduckgo",
      consented: true,
      consent_text: "x",
      can_save_keys: true,
      providers: [],
    };
    const api = createAssistantApi({
      async fetch(path, init) {
        calls.push({ path, init });
        return new Response(JSON.stringify(status), { status: 200 });
      },
    });
    expect((await api.searchStatus()).consented).toBe(true);
    await api.updateSearch({ provider: "tavily", key: { provider: "tavily", value: "tvly-1" } });
    expect(calls[0]?.path).toBe("/products/wasifyai-assistant/search");
    expect(calls[1]?.init?.method).toBe("PUT");
    expect(JSON.parse(calls[1]?.init?.body as string)).toEqual({
      provider: "tavily",
      key: { provider: "tavily", value: "tvly-1" },
    });
  });

  it("lists, reads, renames and deletes", async () => {
    const calls: { path: string; init?: RequestInit }[] = [];
    const api = createAssistantApi({
      async fetch(path, init) {
        calls.push({ path, init });
        if (init?.method === "DELETE") return new Response(null, { status: 204 });
        return new Response(
          JSON.stringify({
            conversations: [{ id: "c1", title: "T", created_at: "", updated_at: "" }],
          }),
          { status: 200 },
        );
      },
    });
    expect((await api.list(5))[0]?.id).toBe("c1");
    expect(calls[0]?.path).toBe("/products/wasifyai-assistant/conversations?limit=5");
    await api.rename("c1", "New");
    expect(calls[1]?.init?.method).toBe("PATCH");
    await expect(api.remove("c1")).resolves.toBeUndefined();
  });
});
