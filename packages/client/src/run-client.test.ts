import { describe, expect, it, vi } from "vitest";
import { createRunClient } from "./run-client";
import { HttpError, type Transport } from "./transport";

function frame(seq: number, name: string, data: Record<string, unknown> = {}): string {
  const body = { run_id: "r1", thread_id: "t", seq, ts: "", ...data };
  return `id: ${seq}\nevent: ${name}\ndata: ${JSON.stringify(body)}\n\n`;
}

function sse(text: string, status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      c.enqueue(new TextEncoder().encode(text));
      c.close();
    },
  });
  return new Response(body, { status, headers: { "content-type": "text/event-stream" } });
}

function setup(answer: (path: string, init?: RequestInit) => Response | Promise<Response>) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const onUnauthorized = vi.fn();
  const transport: Transport = {
    async fetch(path, init) {
      calls.push({ path, init });
      return answer(path, init);
    },
    onUnauthorized,
  };
  return { client: createRunClient(transport), calls, onUnauthorized };
}

describe("runs", () => {
  it("starts a run on the engine path and parses its events", async () => {
    const { client, calls } = setup(() =>
      sse(frame(1, "node", { node: "a", status: "started" }) + frame(2, "done", { outputs: {} })),
    );
    const seen: string[] = [];
    await client.startRun(
      "wasifyai-image",
      { prompt: "a cat" },
      new AbortController().signal,
      (e) => seen.push(e.event),
    );
    expect(seen).toEqual(["node", "done"]);
    expect(calls[0]?.path).toBe("/products/wasifyai-image/runs");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(JSON.parse(calls[0]?.init?.body as string)).toEqual({ input: { prompt: "a cat" } });
  });

  it("re-attaches from the last event it saw", async () => {
    const { client, calls } = setup(() => sse(frame(5, "done", { outputs: {} })));
    await client.watchRun("run-9", 4, new AbortController().signal, () => {});
    expect(calls[0]?.path).toBe("/runs/run-9/events");
    expect(calls[0]?.init?.headers).toMatchObject({ "last-event-id": "4" });
  });

  it("resumes a run with the answer", async () => {
    const { client, calls } = setup(() => sse(frame(9, "done", { outputs: {} })));
    await client.resumeRun("run-9", { action: "approve" }, new AbortController().signal, () => {});
    expect(calls[0]?.path).toBe("/runs/run-9/resume");
    expect(JSON.parse(calls[0]?.init?.body as string)).toEqual({ value: { action: "approve" } });
  });

  it("turns an error answer into an HttpError with the server's words", async () => {
    const { client } = setup(() => Response.json({ detail: "unknown product" }, { status: 404 }));
    const err = await client
      .startRun("nope", {}, new AbortController().signal, () => {})
      .catch((e) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect(err).toMatchObject({ status: 404, message: "unknown product" });
  });

  it("falls back to the status when the body says nothing", async () => {
    const { client } = setup(() => new Response("oops", { status: 502 }));
    const err = await client
      .startRun("p", {}, new AbortController().signal, () => {})
      .catch((e) => e);
    expect(err.message).toBe("The server answered 502");
  });

  it("tells the transport when the session has ended", async () => {
    const { client, onUnauthorized } = setup(() => new Response(null, { status: 401 }));
    await expect(
      client.startRun("p", {}, new AbortController().signal, () => {}),
    ).rejects.toBeInstanceOf(HttpError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});

describe("uploads and enhance", () => {
  it("sends the file itself with its type, and returns the upload", async () => {
    const { client, calls } = setup(() =>
      Response.json({ upload_id: "u1", key: "uploads/u1.png", width: 3, height: 2, bytes: 9 }),
    );
    const file = new File([new Uint8Array(9)], "a.png", { type: "image/png" });
    const up = await client.uploadImage("wasifyai-image", file);
    expect(up.upload_id).toBe("u1");
    expect(calls[0]?.path).toBe("/products/wasifyai-image/uploads/images");
    expect(calls[0]?.init?.headers).toMatchObject({ "content-type": "image/png" });
    expect(calls[0]?.init?.body).toBe(file);
  });

  it("takes back an upload, and never throws for it", async () => {
    const { client, calls } = setup(() => new Response(null, { status: 204 }));
    await client.deleteUpload("wasifyai-image", "u1");
    expect(calls[0]?.path).toBe("/products/wasifyai-image/uploads/images/u1");
    expect(calls[0]?.init).toMatchObject({ method: "DELETE", keepalive: true });

    const failing = createRunClient({
      fetch: async () => {
        throw new Error("offline");
      },
    });
    await expect(failing.deleteUpload("p", "u")).resolves.toBeUndefined();
    await expect(failing.deleteMediaUpload("p", "u")).resolves.toBeUndefined();
  });

  it("enhances a prompt", async () => {
    const { client, calls } = setup(() => Response.json({ prompt: "a better cat", changed: true }));
    const out = await client.enhancePrompt("wasifyai-image", {
      kind: "text_to_image",
      prompt: "cat",
      uploadId: "u1",
    });
    expect(out).toEqual({ prompt: "a better cat", changed: true });
    expect(calls[0]?.path).toBe("/products/wasifyai-image/prompt/enhance");
    expect(JSON.parse(calls[0]?.init?.body as string)).toEqual({
      kind: "text_to_image",
      prompt: "cat",
      upload_id: "u1",
    });
  });
});
