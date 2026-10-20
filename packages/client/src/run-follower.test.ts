import { describe, expect, it } from "vitest";
import { createRunClient } from "./run-client";
import { type RunFollow, followRun, newRunFollow } from "./run-follower";
import type { ParsedEvent } from "./sse";
import { HttpError, type Transport } from "./transport";

const RUN = "5b6c1c1e-0000-4000-8000-000000000001";

function frame(seq: number, name: string, data: Record<string, unknown> = {}): string {
  const body = { run_id: RUN, thread_id: "t", seq, ts: "", ...data };
  return `id: ${seq}\nevent: ${name}\ndata: ${JSON.stringify(body)}\n\n`;
}

const token = (seq: number) => frame(seq, "token", { text: `w${seq} ` });
const done = (seq: number) => frame(seq, "done", { outputs: {} });

/** One answer of the fake engine: the frames, then how the stream ends (cleanly, or broken like a lost connection). */
type Answer = { frames: string; end?: "clean" | "broken" } | { fail: Error } | { status: number };

function stream(a: { frames: string; end?: "clean" | "broken" }): Response {
  let sent = false;
  const body = new ReadableStream<Uint8Array>({
    // the frames reach the reader before the stream breaks, as with a connection that drops mid-answer
    pull(c) {
      if (!sent && a.frames) {
        sent = true;
        c.enqueue(new TextEncoder().encode(a.frames));
        return;
      }
      if (a.end === "broken") c.error(new TypeError("network error"));
      else c.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

/** A transport that answers each request in turn from `answers`, and records what was asked. */
function setup(answers: Answer[]) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const transport: Transport = {
    async fetch(path, init) {
      calls.push({ path, init });
      const a = answers.shift();
      if (!a) throw new TypeError("no more answers");
      if ("fail" in a) throw a.fail;
      if ("status" in a) return Response.json({ detail: "no" }, { status: a.status });
      return stream(a);
    },
  };
  const runs = createRunClient(transport);
  const events: ParsedEvent[] = [];
  const follow = newRunFollow(RUN);
  const sleeps: number[] = [];
  const ctrl = new AbortController();
  const go = (f: RunFollow = follow, extra: { attempts?: number; signal?: AbortSignal } = {}) =>
    followRun(
      f,
      (signal, onEvent) =>
        runs.startRun("wasifyai-assistant", { text: "hi" }, signal, onEvent, f.runId),
      runs.watchRun,
      {
        signal: extra.signal ?? ctrl.signal,
        onEvent: (e) => events.push(e),
        attempts: extra.attempts,
        sleep: async (ms) => {
          sleeps.push(ms);
        },
      },
    );
  const seqs = () => events.map((e) => (e.data as unknown as { seq: number }).seq);
  return { go, calls, events, follow, sleeps, seqs, ctrl, runs };
}

describe("followRun", () => {
  it("starts the run under the id chosen here and follows it to the end", async () => {
    const t = setup([{ frames: token(1) + token(2) + done(3) }]);
    expect(await t.go()).toBe("finished");
    expect(t.seqs()).toEqual([1, 2, 3]);
    expect(t.calls).toHaveLength(1);
    expect(t.calls[0]?.path).toBe("/products/wasifyai-assistant/runs");
    expect(JSON.parse(t.calls[0]?.init?.body as string)).toEqual({
      input: { text: "hi" },
      run_id: RUN,
    });
    expect(t.sleeps).toEqual([]);
  });

  it("re-attaches from the last event after a stream that broke", async () => {
    const t = setup([
      { frames: token(1) + token(2), end: "broken" },
      { frames: token(3) + done(4) },
    ]);
    expect(await t.go()).toBe("finished");
    expect(t.seqs()).toEqual([1, 2, 3, 4]);
    expect(t.calls[1]?.path).toBe(`/runs/${RUN}/events`);
    expect(t.calls[1]?.init?.headers).toMatchObject({ "last-event-id": "2" });
    expect(t.sleeps).toEqual([300]);
  });

  it("re-attaches after a stream that ended cleanly without a closing event", async () => {
    const t = setup([{ frames: token(1) }, { frames: token(2) + done(3) }]);
    expect(await t.go()).toBe("finished");
    expect(t.seqs()).toEqual([1, 2, 3]);
  });

  it("keeps going when the first stream fails with an exception after some events", async () => {
    const t = setup([
      { frames: token(1), end: "broken" },
      { fail: new TypeError("offline") },
      { frames: token(2) + done(3) },
    ]);
    expect(await t.go()).toBe("finished");
    expect(t.seqs()).toEqual([1, 2, 3]);
    expect(t.sleeps).toEqual([300, 800]);
  });

  it("counts only cuts that bring nothing: a run cut again and again after progress still finishes", async () => {
    const answers: Answer[] = [];
    for (let seq = 1; seq <= 10; seq++) answers.push({ frames: token(seq), end: "broken" });
    answers.push({ frames: done(11) });
    const t = setup(answers);
    expect(await t.go()).toBe("finished");
    expect(t.seqs()).toHaveLength(11);
    // every cut came after progress, so the pause never grew
    expect(new Set(t.sleeps)).toEqual(new Set([300]));
  });

  it("starts again under the same id when the connection broke before the first event", async () => {
    const t = setup([{ fail: new TypeError("offline") }, { frames: token(1) + done(2) }]);
    expect(await t.go()).toBe("finished");
    expect(t.calls.map((c) => c.path)).toEqual([
      "/products/wasifyai-assistant/runs",
      "/products/wasifyai-assistant/runs",
    ]);
    expect(t.calls.map((c) => JSON.parse(c.init?.body as string).run_id)).toEqual([RUN, RUN]);
  });

  it("gives up after the attempts, with pauses that grow, and can be picked up again", async () => {
    const t = setup([
      { frames: token(1), end: "broken" },
      { fail: new TypeError("offline") },
      { fail: new TypeError("offline") },
      { fail: new TypeError("offline") },
    ]);
    expect(await t.go(t.follow, { attempts: 3 })).toBe("lost");
    expect(t.sleeps).toEqual([300, 800, 1600]);
    expect(t.follow.finished).toBe(false);
    expect(t.follow.lastSeq).toBe(1);
    // "Try again": the same follow state attaches from where it was, it does not send the message again
    const more = setup([{ frames: token(2) + done(3) }]);
    const again = await followRun(
      t.follow,
      async () => {
        throw new Error("must not start the run again");
      },
      more.runs.watchRun,
      { signal: new AbortController().signal, onEvent: () => {}, sleep: async () => {} },
    );
    expect(again).toBe("finished");
    expect(more.calls[0]?.path).toBe(`/runs/${RUN}/events`);
    expect(more.calls[0]?.init?.headers).toMatchObject({ "last-event-id": "1" });
  });

  it("waits longer than five seconds in total before it gives up", async () => {
    const answers: Answer[] = [{ frames: token(1), end: "broken" }];
    for (let i = 0; i < 20; i++) answers.push({ fail: new TypeError("offline") });
    const t = setup(answers);
    expect(await t.go()).toBe("lost");
    expect(t.sleeps.reduce((a, b) => a + b, 0)).toBeGreaterThan(20_000);
    expect(Math.max(...t.sleeps)).toBeLessThanOrEqual(5000);
  });

  it("does not retry an answer that will not change (a refusal from the engine)", async () => {
    const t = setup([{ status: 422 }]);
    await expect(t.go()).rejects.toBeInstanceOf(HttpError);
    expect(t.calls).toHaveLength(1);
  });

  it("retries an engine error that may pass", async () => {
    const t = setup([{ status: 503 }, { frames: token(1) + done(2) }]);
    expect(await t.go()).toBe("finished");
  });

  it("follows the id the engine gives the run when it did not take the one chosen here", async () => {
    const t = setup([
      { frames: frame(1, "token", { run_id: "engine-run", text: "a" }), end: "broken" },
      { frames: frame(2, "done", { run_id: "engine-run", outputs: {} }) },
    ]);
    expect(await t.go()).toBe("finished");
    expect(t.follow.runId).toBe("engine-run");
    expect(t.calls[1]?.path).toBe("/runs/engine-run/events");
  });

  it("treats an interrupt as the end of the stream", async () => {
    const t = setup([
      {
        frames:
          token(1) +
          frame(2, "interrupt", { interrupt_id: "i", kind: "confirm_action", payload: {} }),
      },
    ]);
    expect(await t.go()).toBe("finished");
    expect(t.calls).toHaveLength(1);
  });

  it("stops quietly when the caller aborts", async () => {
    const t = setup([{ frames: token(1), end: "broken" }]);
    const outcome = t.go();
    t.ctrl.abort();
    expect(await outcome).toBe("aborted");
  });
});

describe("followRun waiting", () => {
  it("wakes at once when the network comes back instead of waiting out the pause", async () => {
    const calls: string[] = [];
    const fetcher: Transport["fetch"] = async (path) => {
      calls.push(path);
      if (calls.length === 1) return stream({ frames: token(1), end: "broken" });
      return stream({ frames: token(2) + done(3) });
    };
    const runs = createRunClient({ fetch: fetcher });
    let fire: () => void = () => {};
    const started = Date.now();
    const outcome = followRun(
      newRunFollow(RUN),
      (s, e) => runs.startRun("p", {}, s, e, RUN),
      runs.watchRun,
      {
        signal: new AbortController().signal,
        onEvent: () => {},
        delay: () => 60_000, // would hang the test for a minute if `online` did not wake it
        onOnline: (cb) => {
          fire = cb;
          return () => {};
        },
      },
    );
    await new Promise((r) => setTimeout(r, 20));
    fire();
    expect(await outcome).toBe("finished");
    expect(Date.now() - started).toBeLessThan(5000);
  });
});
