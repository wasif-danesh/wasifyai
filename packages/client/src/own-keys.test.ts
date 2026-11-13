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
  it("keeps keys per provider and chooses a cloud model on /desktop/keys", async () => {
    const { transport, calls } = fake((path) =>
      json(
        path.endsWith("/test")
          ? { ok: true, ms: 9, said: null }
          : path.endsWith("/cloud") || path.endsWith("/use")
            ? { product: "lipsync", models: [], has_keys: true }
            : view,
      ),
    );
    const api = createOwnKeysApi(transport);
    await api.list();
    const t = await api.test("lipsync", "fal", { key: "k1" });
    await api.save("lipsync", "fal", { key: "k2" });
    await api.check("lipsync", "fal");
    await api.remove("lipsync", "fal");
    await api.cloud("lipsync");
    await api.use("lipsync", { provider: "fal", model: "fal-ai/infinitalk" });
    await api.use("lipsync", null);
    expect(t).toEqual({ ok: true, ms: 9, said: null });
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["GET", "/desktop/keys"],
      ["POST", "/desktop/keys/lipsync/keys/fal/test"],
      ["PUT", "/desktop/keys/lipsync/keys/fal"],
      ["POST", "/desktop/keys/lipsync/keys/fal/check"],
      ["DELETE", "/desktop/keys/lipsync/keys/fal"],
      ["GET", "/desktop/keys/lipsync/cloud"],
      ["PUT", "/desktop/keys/lipsync/use"],
      ["PUT", "/desktop/keys/lipsync/use"],
    ]);
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({ key: "k2" });
    expect(JSON.parse(String(calls[6]?.init?.body))).toEqual({
      provider: "fal",
      model: "fal-ai/infinitalk",
    });
    expect(JSON.parse(String(calls[7]?.init?.body))).toEqual({ provider: null });
  });

  it("passes on the engine's words when a key is refused", async () => {
    const { transport } = fake(() => json({ detail: "fal.ai did not accept the key." }, 422));
    const err = await createOwnKeysApi(transport)
      .save("images", "fal", { key: "bad" })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect((err as HttpError).message).toContain("fal.ai did not accept the key.");
  });
});
