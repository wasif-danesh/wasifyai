import { describe, expect, it } from "vitest";
import { type AskState, askReducer, createNotebooksApi, initialAsk, isWorking } from "./notebooks";
import type { ParsedEvent } from "./sse";
import { HttpError, type Transport } from "./transport";

const ev = (event: string, data: Record<string, unknown>, seq = 1): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq, ...data } }) as ParsedEvent;

function run(events: ParsedEvent[], from: AskState = initialAsk): AskState {
  let s = askReducer(from, { type: "submitted", text: "What is the budget?", id: "u1" });
  for (const e of events) s = askReducer(s, { type: "event", event: e });
  return s;
}

describe("a question and its answer", () => {
  it("shows the search, streams the answer, then replaces it with the checked one", () => {
    let s = askReducer(initialAsk, { type: "submitted", text: "Budget?", id: "u1" });
    expect(isWorking(s)).toBe(true);
    s = askReducer(s, {
      type: "event",
      event: ev("tool_call", { id: "c", name: "search_sources", arguments: { sources: 12 } }, 2),
    });
    expect(s.messages[1]?.searched).toEqual({ sources: 12, passages: 0 });
    s = askReducer(s, {
      type: "event",
      event: ev("tool_result", { id: "c", name: "search_sources", output: { hits: [{}, {}] } }, 3),
    });
    expect(s.phase).toBe("answering");
    expect(s.messages[1]?.searched).toEqual({ sources: 12, passages: 2 });
    s = askReducer(s, {
      type: "event",
      event: ev("token", { text: "It is $350,000 [1] [n]." }, 4),
    });
    expect(s.messages[1]?.text).toBe("It is $350,000 [1] [n].");
    const cite = {
      n: 1,
      chunk_id: 9,
      document_id: "d",
      title: "budget.txt",
      start_line: 1,
      end_line: 3,
      text: "…",
    };
    s = askReducer(s, {
      type: "event",
      event: ev(
        "done",
        {
          outputs: {
            status: "done",
            reply: "It is $350,000 [1].",
            citations: [cite],
            conversation_id: "c1",
            title: "Budget?",
          },
        },
        5,
      ),
    });
    expect(s.phase).toBe("idle");
    expect(s.messages[1]).toMatchObject({ text: "It is $350,000 [1].", streaming: false });
    expect(s.messages[1]?.citations).toEqual([cite]);
    expect(s.conversationId).toBe("c1");
    expect(s.title).toBe("Budget?");
    expect(s.lastSeq).toBe(5);
  });

  it("ignores other tools, and says why a question was not sent", () => {
    const s = run([ev("tool_call", { id: "x", name: "something_else", arguments: {} })]);
    expect(s.messages[1]?.searched).toBeUndefined();
    const refused = run([
      ev("done", {
        outputs: {
          status: "refused",
          refusal: { code: "no_sources", message: "Add a source first." },
        },
      }),
    ]);
    expect(refused.phase).toBe("error");
    expect(refused.error).toEqual({
      code: "no_sources",
      message: "Add a source first.",
      retryable: false,
    });
    expect(refused.messages.map((m) => m.role)).toEqual(["user"]); // the empty reply is gone
  });

  it("keeps the question and drops the empty reply on an error, and can be stopped", () => {
    const failed = run([
      ev("error", {
        code: "embedder_missing",
        message: "The search model is not here.",
        retryable: false,
      }),
    ]);
    expect(failed.phase).toBe("error");
    expect(failed.error?.code).toBe("embedder_missing");
    expect(failed.messages).toHaveLength(1);
    const stopped = askReducer(askReducer(initialAsk, { type: "submitted", text: "q", id: "u" }), {
      type: "stopped",
    });
    expect(stopped.phase).toBe("idle");
    expect(stopped.messages).toHaveLength(1);
  });

  it("opens a saved conversation with its citations", () => {
    const s = askReducer(initialAsk, {
      type: "loaded",
      conversation: {
        id: "c1",
        notebook_id: "n",
        title: "Budget",
        created_at: "",
        updated_at: "",
        messages: [
          { id: "m1", seq: 1, role: "user", text: "Q?", citations: [], created_at: "" },
          {
            id: "m2",
            seq: 2,
            role: "assistant",
            text: "A [1].",
            citations: [
              {
                n: 1,
                chunk_id: 1,
                document_id: "d",
                title: "t",
                start_line: 1,
                end_line: 1,
                text: "x",
              },
            ],
            created_at: "",
          },
        ],
      },
    });
    expect(s.conversationId).toBe("c1");
    expect(s.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(s.messages[1]?.citations).toHaveLength(1);
  });
});

describe("the notebooks api", () => {
  function api(handler: (path: string, init?: RequestInit) => Response) {
    const calls: { path: string; init?: RequestInit }[] = [];
    const transport: Transport = {
      fetch: async (path, init) => {
        calls.push({ path, init });
        return handler(path, init);
      },
    };
    return { api: createNotebooksApi(transport), calls };
  }

  it("creates, uploads with the folder, and reads a refusal in words", async () => {
    const { api: a, calls } = api((path) =>
      path.endsWith("/documents/upload")
        ? new Response(
            JSON.stringify({
              created: [],
              duplicates: [],
              rejected: [{ name: "x.exe", reason: "No." }],
            }),
            { status: 201 },
          )
        : new Response(JSON.stringify({ id: "n1", title: "Untitled notebook" }), { status: 201 }),
    );
    expect((await a.create()).id).toBe("n1");
    expect(calls[0]?.init?.body).toBe("{}");
    const file = new File(["hi"], "a.txt", { type: "text/plain" });
    const out = await a.upload("n1", [file], "f1");
    expect(out.rejected[0]?.name).toBe("x.exe");
    const form = calls[1]?.init?.body as FormData;
    expect(form.get("folder_id")).toBe("f1");
    expect((form.get("files") as File).name).toBe("a.txt");

    const { api: b } = api(
      () =>
        new Response(
          JSON.stringify({
            detail: { code: "embedder_missing", message: "Get the search model." },
          }),
          {
            status: 409,
          },
        ),
    );
    await expect(b.setupReader(1)).rejects.toThrow("Get the search model.");
    await expect(b.setupReader(1)).rejects.toBeInstanceOf(HttpError);
  });

  it("finds notebooks through My creations search, only this product's", async () => {
    const { api: a, calls } = api(
      () =>
        new Response(
          JSON.stringify({
            results: [
              { id: "n1", product_id: "wasifyai-notebooks" },
              { id: "i1", product_id: "wasifyai-image" },
            ],
          }),
        ),
    );
    expect(await a.find("budget plan")).toEqual(["n1"]);
    expect(calls[0]?.path).toContain("kind=notebook");
    expect(calls[0]?.path).toContain("q=budget+plan");
  });
});

describe("making an output", () => {
  const runs = (events: ParsedEvent[], seen: object[] = []) => ({
    startRun: async (_p: string, input: object, _s: AbortSignal, on: (e: ParsedEvent) => void) => {
      seen.push(input);
      for (const e of events) on(e);
    },
  });

  it("sends the format, the focus and the ticked sources, and returns the saved output", async () => {
    const seen: object[] = [];
    const steps: string[] = [];
    const { makeOutput } = await import("./notebooks");
    const out = await makeOutput(
      runs(
        [
          ev("node", { node: "read", status: "started", label: "Reading your sources" }, 1),
          ev("done", { outputs: { status: "done", artifact_id: "a1", title: "Launch plan" } }, 2),
        ],
        seen,
      ),
      { notebookId: "n1", format: "report", prompt: "the launch", documentIds: ["d1"] },
      new AbortController().signal,
      (s) => steps.push(s),
    );
    expect(out).toEqual({ ok: true, outputId: "a1", title: "Launch plan" });
    expect(steps).toEqual(["Reading your sources"]);
    expect(seen[0]).toEqual({
      notebook_id: "n1",
      studio: { format: "report", prompt: "the launch" },
      document_ids: ["d1"],
    });
  });

  it("says why it was not made, from a refusal or an error", async () => {
    const { makeOutput } = await import("./notebooks");
    const ask = { notebookId: "n1", format: "quiz" as const, prompt: "" };
    const signal = new AbortController().signal;
    const refused = await makeOutput(
      runs([
        ev("done", {
          outputs: { status: "refused", refusal: { code: "no_scope", message: "None ticked." } },
        }),
      ]),
      ask,
      signal,
    );
    expect(refused).toEqual({ ok: false, code: "no_scope", message: "None ticked." });
    const failed = await makeOutput(
      runs([ev("error", { code: "language_failed", message: "The model did not answer." })]),
      ask,
      signal,
    );
    expect(failed).toMatchObject({ ok: false, code: "language_failed" });
    const none = await makeOutput(runs([]), ask, signal);
    expect(none).toMatchObject({ ok: false, code: "lost" });
  });
});
