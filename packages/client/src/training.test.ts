import { describe, expect, it } from "vitest";
import { createTrainingApi } from "./training";
import { HttpError, type Transport } from "./transport";

type Call = { path: string; init?: RequestInit };

function fake(answer: (path: string, init?: RequestInit) => Response) {
  const calls: Call[] = [];
  let unauthorized = 0;
  const transport: Transport = {
    async fetch(path, init) {
      calls.push({ path, init });
      return answer(path, init);
    },
    onUnauthorized() {
      unauthorized += 1;
    },
  };
  return { transport, calls, unauthorized: () => unauthorized };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const BASE = "/products/wasifyai-training/train";

describe("the training client", () => {
  it("makes a set, changes it and removes it on the product's routes", async () => {
    const { transport, calls } = fake(() => json({ id: "d1" }));
    const api = createTrainingApi(transport);
    await api.createDataset("style", "Ink");
    await api.updateDataset("d1", { trigger_word: "zorbak", rights: "mine" });
    await api.dataset("d1");
    await api.removeDataset("d1");
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["POST", `${BASE}/datasets`],
      ["PATCH", `${BASE}/datasets/d1`],
      ["GET", `${BASE}/datasets/d1`],
      ["DELETE", `${BASE}/datasets/d1`],
    ]);
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ kind: "style", name: "Ink" });
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({
      trigger_word: "zorbak",
      rights: "mine",
    });
  });

  it("sends a picture as the body with its own type, and the name in the address", async () => {
    const { transport, calls } = fake(() => json({ id: "p1" }));
    const api = createTrainingApi(transport);
    const file = new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });
    await api.addPicture("d1", file, "my frog.png");
    expect(calls[0]?.path).toBe(`${BASE}/datasets/d1/items?name=my%20frog.png`);
    expect(calls[0]?.init?.method).toBe("POST");
    expect((calls[0]?.init?.headers as Record<string, string>)["content-type"]).toBe("image/png");
    expect(calls[0]?.init?.body).toBe(file);
  });

  it("writes descriptions for all, or again for some, and edits one", async () => {
    const { transport, calls } = fake(() => json({ writing: 2 }));
    const api = createTrainingApi(transport);
    await api.writeCaptions("d1");
    await api.writeCaptions("d1", { again: true, pictureIds: ["p1"] });
    await api.editCaption("d1", "p1", "On a hill.");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ again: false, item_ids: null });
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({ again: true, item_ids: ["p1"] });
    expect(calls[2]?.path).toBe(`${BASE}/datasets/d1/items/p1`);
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({ caption: "On a hill." });
  });

  it("starts, follows and stops a run, and lists and renames the models", async () => {
    const { transport, calls } = fake((path) =>
      path.endsWith("/runs") && !path.includes("?")
        ? json({ runs: [] })
        : json({ models: [], id: "r1" }),
    );
    const api = createTrainingApi(transport);
    await api.startRun("d1");
    await api.run("r1");
    await api.cancelRun("r1");
    await api.models();
    await api.renameModel("m1", "Marlo");
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["POST", `${BASE}/runs`],
      ["GET", `${BASE}/runs/r1`],
      ["POST", `${BASE}/runs/r1/cancel`],
      ["GET", `${BASE}/models`],
      ["PATCH", `${BASE}/models/m1`],
    ]);
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ dataset_id: "d1" });
  });

  it("turns a picture into an object URL, once asked", async () => {
    const created: Blob[] = [];
    const original = URL.createObjectURL;
    URL.createObjectURL = (b: Blob | MediaSource) => {
      created.push(b as Blob);
      return "blob:x";
    };
    try {
      const { transport, calls } = fake(() => new Response(new Blob(["png"]), { status: 200 }));
      const api = createTrainingApi(transport);
      expect(await api.pictureUrl("d1", "p1", "thumb")).toBe("blob:x");
      expect(await api.sampleUrl("r1", "step 1.png")).toBe("blob:x");
      expect(calls.map((c) => c.path)).toEqual([
        `${BASE}/datasets/d1/items/p1/thumb`,
        `${BASE}/runs/r1/samples/step%201.png`,
      ]);
    } finally {
      URL.createObjectURL = original;
    }
  });

  it("says why in the engine's words, and tells the app when the session ended", async () => {
    const { transport, unauthorized } = fake((path) =>
      path.endsWith("/status")
        ? new Response("sign in", { status: 401 })
        : json(
            {
              detail: { code: "busy", message: "A model is being taught. Wait for it to finish." },
            },
            409,
          ),
    );
    const api = createTrainingApi(transport);
    await expect(api.startRun("d1")).rejects.toThrowError(HttpError);
    await expect(api.startRun("d1")).rejects.toThrow("A model is being taught");
    await expect(api.status()).rejects.toBeInstanceOf(HttpError);
    expect(unauthorized()).toBe(1);
  });
});
