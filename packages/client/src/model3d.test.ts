import { afterEach, describe, expect, it, vi } from "vitest";
import { createModel3dApi, gigabytes, minutes } from "./model3d";
import { HttpError, type Transport } from "./transport";

type Call = { path: string; init?: RequestInit };

function fake(answer: (path: string, init?: RequestInit) => Response): {
  transport: Transport;
  calls: Call[];
  unauthorized: number;
} {
  const out = { calls: [] as Call[], unauthorized: 0 };
  const transport: Transport = {
    async fetch(path, init) {
      out.calls.push({ path, init });
      return answer(path, init);
    },
    onUnauthorized() {
      out.unauthorized += 1;
    },
  };
  return {
    transport,
    calls: out.calls,
    get unauthorized() {
      return out.unauthorized;
    },
  };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const BASE = "/products/wasifyai-model3d/m3d";

afterEach(() => vi.restoreAllMocks());

describe("the 3D client", () => {
  it("reads the component and sets it up with the size the person was shown", async () => {
    const { transport, calls } = fake(() => json({ installed: false }));
    const api = createModel3dApi(transport);
    await api.component();
    await api.install(8_977_179_071);
    await api.cancelInstall();
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["GET", "/desktop/model3d"],
      ["POST", "/desktop/model3d/install"],
      ["POST", "/desktop/model3d/install/cancel"],
    ]);
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({ confirm_bytes: 8_977_179_071 });
  });

  it("sends a picture as the body, with its own type, and follows it", async () => {
    const { transport, calls } = fake(() => json({ id: "p1", status: "checking" }));
    const api = createModel3dApi(transport);
    const file = new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });
    await api.addPicture(file, "my frog.png");
    await api.picture("p1");
    expect(calls[0]?.path).toBe(`${BASE}/inputs?name=my%20frog.png`);
    expect(calls[0]?.init?.method).toBe("POST");
    expect((calls[0]?.init?.headers as Record<string, string>)["content-type"]).toBe("image/png");
    expect(calls[0]?.init?.body).toBe(file);
    expect(calls[1]?.path).toBe(`${BASE}/inputs/p1`);
  });

  it("makes a model, follows it, stops it, makes it again, renames it and deletes it", async () => {
    const { transport, calls } = fake(() => json({ id: "m1", status: "working" }));
    const api = createModel3dApi(transport);
    await api.make({ input_id: "p1", title: "Frog", detail: "light", seed: 3 });
    await api.get("m1");
    await api.cancel("m1");
    await api.again("m1");
    await api.rename("m1", "Green frog");
    await api.exportCopy("m1");
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["POST", `${BASE}/models`],
      ["GET", `${BASE}/models/m1`],
      ["POST", `${BASE}/models/m1/cancel`],
      ["POST", `${BASE}/models/m1/again`],
      ["PATCH", `${BASE}/models/m1`],
      ["POST", `${BASE}/models/m1/export`],
    ]);
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      input_id: "p1",
      title: "Frog",
      detail: "light",
      seed: 3,
    });
    expect(JSON.parse(String(calls[4]?.init?.body))).toEqual({ title: "Green frog" });
  });

  it("lists the models and treats a model that is already gone as deleted", async () => {
    const list = fake(() => json({ items: [{ id: "m1" }] }));
    expect(await createModel3dApi(list.transport).list()).toEqual([{ id: "m1" }]);
    const gone = fake(() => json({ detail: "3D model not found" }, 404));
    await expect(createModel3dApi(gone.transport).remove("m1")).resolves.toBeUndefined();
    await expect(createModel3dApi(gone.transport).removePicture("p1")).resolves.toBeUndefined();
    const broken = fake(() => json({ detail: "boom" }, 500));
    await expect(createModel3dApi(broken.transport).remove("m1")).rejects.toBeInstanceOf(HttpError);
  });

  it("shows files as pictures and models the window can use, through the transport", async () => {
    const make = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:glb-1");
    const { transport, calls } = fake(
      () =>
        new Response(new Uint8Array([103, 108, 84, 70]), {
          headers: { "content-type": "model/gltf-binary" },
        }),
    );
    const api = createModel3dApi(transport);
    expect(await api.fileUrl("m1", "file")).toBe("blob:glb-1");
    await api.fileUrl("m1", "thumb");
    await api.pictureImage("p1", "cutout");
    expect(calls.map((c) => c.path)).toEqual([
      `${BASE}/models/m1/file`,
      `${BASE}/models/m1/thumb`,
      `${BASE}/inputs/p1/cutout`,
    ]);
    expect(make).toHaveBeenCalledTimes(3);
  });

  it("says what went wrong in the engine's own words and tells the app when the session ended", async () => {
    const refused = fake(() =>
      json(
        {
          detail: {
            code: "busy",
            message: "A 3D model is already being made. Wait for it to finish.",
          },
        },
        409,
      ),
    );
    const err = await createModel3dApi(refused.transport)
      .make({ input_id: "p1" })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect((err as HttpError).status).toBe(409);
    expect((err as HttpError).message).toBe(
      "A 3D model is already being made. Wait for it to finish.",
    );
    const ended = fake(() => json({ detail: "no" }, 401));
    await createModel3dApi(ended.transport)
      .status()
      .catch(() => {});
    expect(ended.unauthorized).toBe(1);
  });

  it("writes times and sizes for a person", () => {
    expect(minutes(30)).toBe("about a minute");
    expect(minutes(611)).toBe("about 10 minutes");
    expect(gigabytes(8_977_179_071)).toBe("9.0 GB");
    expect(gigabytes(2_440_967)).toBe("2 MB");
  });
});
