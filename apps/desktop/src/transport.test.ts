import { describe, expect, it, vi } from "vitest";
import type { EngineSession } from "./engine";
import { createEngineTransport } from "./transport";

const session = (n: number, expires: number): EngineSession => ({
  base_url: `http://127.0.0.1:${4000 + n}`,
  token: `token-${n}`,
  expires_at: expires,
});

function setup(sessions: EngineSession[], answers: Response[], t = 1_000_000) {
  let clock = t;
  const getSession = vi.fn(async () => {
    const s = sessions.shift();
    if (!s) throw new Error("no more sessions");
    return s;
  });
  const calls: { url: string; auth: string | null }[] = [];
  const fetchFn = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(url), auth: new Headers(init?.headers).get("authorization") });
    return answers.shift() ?? new Response(null, { status: 200 });
  }) as unknown as typeof fetch;
  const transport = createEngineTransport(getSession, { now: () => clock, fetch: fetchFn });
  return {
    transport,
    getSession,
    calls,
    advance: (ms: number) => {
      clock += ms;
    },
  };
}

describe("the engine transport", () => {
  it("sends engine paths to the engine's address with the shell's token", async () => {
    const { transport, calls } = setup([session(1, 2_000)], []);
    await transport.fetch("/products/wasifyai-image/runs", { method: "POST" });
    expect(calls[0]).toEqual({
      url: "http://127.0.0.1:4001/products/wasifyai-image/runs",
      auth: "Bearer token-1",
    });
  });

  it("keeps the headers the caller set", async () => {
    let seen: Headers | undefined;
    const t = createEngineTransport(async () => session(1, 2_000), {
      now: () => 1_000_000,
      fetch: (async (_u: RequestInfo | URL, init?: RequestInit) => {
        seen = new Headers(init?.headers);
        return new Response(null);
      }) as typeof fetch,
    });
    await t.fetch("/x", { headers: { "last-event-id": "4", accept: "text/event-stream" } });
    expect(seen?.get("last-event-id")).toBe("4");
    expect(seen?.get("accept")).toBe("text/event-stream");
    expect(seen?.get("authorization")).toBe("Bearer token-1");
  });

  it("asks once for a token while it is good, and again shortly before it ends", async () => {
    const { transport, getSession, advance } = setup(
      [session(1, 1_000 + 600), session(2, 1_000 + 2_000)],
      [],
      1_000_000,
    );
    await transport.fetch("/a");
    await transport.fetch("/b");
    expect(getSession).toHaveBeenCalledTimes(1);
    advance(560_000); // 40 s before it expires: inside the refresh margin
    await transport.fetch("/c");
    expect(getSession).toHaveBeenCalledTimes(2);
  });

  it("shares one request for a token between calls made at the same time", async () => {
    const { transport, getSession } = setup([session(1, 2_000)], []);
    await Promise.all([transport.fetch("/a"), transport.fetch("/b"), transport.fetch("/c")]);
    expect(getSession).toHaveBeenCalledTimes(1);
  });

  it("tries again with a fresh token after a 401, once", async () => {
    const { transport, getSession, calls } = setup(
      [session(1, 2_000), session(2, 2_000)],
      [new Response(null, { status: 401 }), new Response("ok", { status: 200 })],
    );
    const res = await transport.fetch("/me");
    expect(res.status).toBe(200);
    expect(getSession).toHaveBeenCalledTimes(2);
    expect(calls.map((c) => c.auth)).toEqual(["Bearer token-1", "Bearer token-2"]);

    const second = setup(
      [session(1, 2_000), session(2, 2_000)],
      [new Response(null, { status: 401 }), new Response(null, { status: 401 })],
    );
    expect((await second.transport.fetch("/me")).status).toBe(401); // gives up: not a loop
    expect(second.calls).toHaveLength(2);
  });

  it("forgets the token when told the engine was restarted", async () => {
    const { transport, getSession, calls } = setup([session(1, 2_000), session(2, 2_000)], []);
    await transport.fetch("/a");
    transport.invalidate();
    await transport.fetch("/b");
    expect(getSession).toHaveBeenCalledTimes(2);
    expect(calls[1]?.url).toBe("http://127.0.0.1:4002/b");
  });
});
