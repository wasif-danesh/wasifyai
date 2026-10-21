import { describe, expect, it } from "vitest";
import { HttpError, type Transport } from "./transport";
import { canExtend, clipLength, createVideosApi } from "./videos";

type Call = { path: string; init?: RequestInit };

function fake(answers: Record<string, () => Response>): { transport: Transport; calls: Call[] } {
  const calls: Call[] = [];
  const transport: Transport = {
    async fetch(path, init) {
      calls.push({ path, init });
      const key = Object.keys(answers).find((k) => path.startsWith(k));
      if (!key) throw new Error(`unexpected ${path}`);
      return answers[key]();
    },
  };
  return { transport, calls };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("videos api", () => {
  it("lists with a limit, a cursor and the status filter", async () => {
    const { transport, calls } = fake({
      "/products/wasifyai-video/videos": () => json({ videos: [], next_before: null }),
    });
    await createVideosApi(transport).list({
      limit: 10,
      before: "2026-10-01T00:00:00Z",
      status: "working",
    });
    expect(calls[0].path).toBe(
      "/products/wasifyai-video/videos?limit=10&before=2026-10-01T00%3A00%3A00Z&status=working",
    );
  });

  it("turns search results into the cards, in the order found", async () => {
    const { transport, calls } = fake({
      "/creations/search": () => json({ results: [{ id: "b" }, { id: "a" }] }),
      "/products/wasifyai-video/videos?ids=": () => json({ videos: [{ id: "b" }, { id: "a" }] }),
    });
    const found = await createVideosApi(transport).search("a fox");
    expect(found.map((v) => v.id)).toEqual(["b", "a"]);
    expect(calls[0].path).toBe("/creations/search?q=a+fox&kind=video&limit=24");
    expect(calls[1].path).toBe("/products/wasifyai-video/videos?ids=b,a");
  });

  it("asks nothing more when nothing matched", async () => {
    const { transport, calls } = fake({ "/creations/search": () => json({ results: [] }) });
    expect(await createVideosApi(transport).search("zzz")).toEqual([]);
    expect(calls).toHaveLength(1);
  });

  it("opens, exports and deletes one clip", async () => {
    const { transport, calls } = fake({
      "/products/wasifyai-video/videos/v1/export": () => json({ name: "a.mp4", path: "/d/a.mp4" }),
      "/products/wasifyai-video/videos/v1": () => json({ id: "v1" }),
    });
    const api = createVideosApi(transport);
    expect((await api.get("v1")).id).toBe("v1");
    expect(await api.exportCopy("v1")).toEqual({ name: "a.mp4", path: "/d/a.mp4" });
    expect(calls[1].init?.method).toBe("POST");
    await api.remove("v1");
    expect(calls[2].init?.method).toBe("DELETE");
  });

  it("treats a clip that is already gone as deleted, and reports other failures", async () => {
    const gone = fake({ "/products/wasifyai-video/videos/v1": () => json({}, 404) });
    await expect(createVideosApi(gone.transport).remove("v1")).resolves.toBeUndefined();
    const broken = fake({
      "/products/wasifyai-video/videos/v1": () =>
        json({ detail: "That video is still being made." }, 409),
    });
    await expect(createVideosApi(broken.transport).remove("v1")).rejects.toBeInstanceOf(HttpError);
  });

  it("names a length", () => {
    expect(clipLength(5)).toBe("5 s");
  });

  it("offers to carry on only the clips that are short enough", () => {
    expect([2, 3, 4].map((seconds) => canExtend({ seconds }))).toEqual([true, true, true]);
    expect([5, 6].map((seconds) => canExtend({ seconds }))).toEqual([false, false]);
    // a video the person added is not held to the length of one the model made
    expect(canExtend({ seconds: 12, mode: "import" })).toBe(true);
    expect(canExtend({ seconds: 12, mode: "text" })).toBe(false);
  });

  it("sends an added video file as a form and answers with the new video", async () => {
    const calls: { path: string; init?: RequestInit }[] = [];
    const transport: Transport = {
      async fetch(path, init) {
        calls.push({ path, init });
        return json({ id: "v9", mode: "import", status: "done" }, 201);
      },
    };
    const file = new File(["x"], "holiday.mp4", { type: "video/mp4" });
    const made = await createVideosApi(transport).importVideo(file);
    expect(made.id).toBe("v9");
    expect(calls[0]?.path).toBe("/products/wasifyai-video/videos/import");
    expect(calls[0]?.init?.method).toBe("POST");
    expect((calls[0]?.init?.body as FormData).get("file")).toBeInstanceOf(File);
    const refused = fake({
      "/products/wasifyai-video/videos/import": () =>
        json({ detail: "That file is not a video." }, 422),
    });
    await expect(createVideosApi(refused.transport).importVideo(file)).rejects.toThrow(
      "That file is not a video.",
    );
  });
});
