import { describe, expect, it } from "vitest";
import { createOwnKeysApi } from "./own-keys";
import { HttpError, type Transport } from "./transport";

type Call = { path: string; init?: RequestInit };

function fake(answer: (path: string, init?: RequestInit) => Response) {
  const calls: Call[] = [];
  const transport: Transport = {
    async fetch(path, init) {
      calls.push({ path, init });
      return answer(path, init);
    },
    onUnauthorized() {},
  };
  return { transport, calls };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const view = { products: [], providers: [], can_save: true };

describe("the own keys client", () => {
  it("lists, tests, saves, checks, copies and removes on /desktop/keys", async () => {
    const { transport, calls } = fake((path) =>
      json(path.endsWith("/test") ? { ok: true, ms: 9, said: null } : view),
    );
    const api = createOwnKeysApi(transport);
    await api.list();
    const t = await api.test("images", { provider: "fal", model: "fal-ai/flux-2", key: "k1" });
    await api.save("images", "key", { provider: "fal", model: "fal-ai/flux-2", key: "k1" });
    await api.save("chat", "here");
    await api.check("images");
    await api.copy("voice", "images");
    await api.remove("images");
    expect(t).toEqual({ ok: true, ms: 9, said: null });
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["GET", "/desktop/keys"],
      ["POST", "/desktop/keys/images/test"],
      ["PUT", "/desktop/keys/images"],
      ["PUT", "/desktop/keys/chat"],
      ["POST", "/desktop/keys/images/check"],
      ["POST", "/desktop/keys/voice/copy"],
      ["DELETE", "/desktop/keys/images"],
    ]);
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({
      mode: "key",
      provider: "fal",
      model: "fal-ai/flux-2",
      key: "k1",
    });
    expect(JSON.parse(String(calls[3]?.init?.body))).toEqual({ mode: "here" });
    expect(JSON.parse(String(calls[5]?.init?.body))).toEqual({ source: "images" });
  });

  it("passes on the engine's words when a key is refused", async () => {
    const { transport } = fake(() => json({ detail: "fal.ai did not accept the key." }, 422));
    const err = await createOwnKeysApi(transport)
      .save("images", "key", { provider: "fal", model: "m", key: "bad" })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect((err as HttpError).message).toContain("fal.ai did not accept the key.");
  });
});
