import { describe, expect, it } from "vitest";
import { createCreationsApi } from "./creations";
import type { Transport } from "./transport";

type Call = { path: string; init?: RequestInit };

function fake(answer: (path: string, init?: RequestInit) => Response) {
  const calls: Call[] = [];
  const transport: Transport = {
    async fetch(path, init) {
      calls.push({ path, init });
      return answer(path, init);
    },
  };
  return { api: createCreationsApi(transport), calls };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("the Library's own calls (ADR-0093, U8)", () => {
  it("deletes each kind through its product's own route, and a thing already gone is no error", async () => {
    const { api, calls } = fake(
      (path) => new Response(null, { status: path.includes("gone") ? 404 : 204 }),
    );
    await api.remove("image", "i1");
    await api.remove("track", "t1");
    await api.remove("notebook", "n1");
    await api.remove("taught", "m1");
    await api.remove("video", "gone");
    expect(calls.map((c) => [c.init?.method, c.path])).toEqual([
      ["DELETE", "/products/wasifyai-image/images/i1"],
      ["DELETE", "/products/wasifyai-voice/tracks/t1"],
      ["DELETE", "/products/wasifyai-notebooks/notebooks/n1"],
      ["DELETE", "/products/wasifyai-training/train/models/m1"],
      ["DELETE", "/products/wasifyai-video/videos/gone"],
    ]);
    const failing = fake(() => json({ detail: "No." }, 500));
    await expect(failing.api.remove("image", "i1")).rejects.toThrow();
  });

  it("finds what was made from a picture (pictures and clips), a clip, and a track", async () => {
    const { api, calls } = fake((path) => {
      if (path.startsWith("/products/wasifyai-image/images")) {
        return json({ images: [{ id: "i2" }], next_before: null });
      }
      if (path.startsWith("/products/wasifyai-video/videos")) {
        return json({ videos: [{ id: "v2" }], next_before: null });
      }
      return json({
        items: [
          { id: "c1", title: "a", created_at: "", audio_url: "", parent_id: "t1" },
          { id: "c2", title: "b", created_at: "", audio_url: "", parent_id: "other" },
        ],
      });
    });
    const fromPicture = await api.madeFrom("image", "i1");
    expect(fromPicture.images.map((i) => i.id)).toEqual(["i2"]);
    expect(fromPicture.videos.map((v) => v.id)).toEqual(["v2"]);
    expect(calls.map((c) => c.path)).toEqual([
      "/products/wasifyai-image/images?limit=24&source=i1",
      "/products/wasifyai-video/videos?limit=24&source=i1",
    ]);
    const fromClip = await api.madeFrom("video", "v1");
    expect(fromClip.images).toEqual([]);
    expect(calls.at(-1)?.path).toBe("/products/wasifyai-video/videos?limit=24&source=v1");
    const fromTrack = await api.madeFrom("track", "t1");
    expect(fromTrack.songs.map((s) => [s.id, s.parent_id])).toEqual([["c1", "t1"]]);
  });

  it("adds a recording to the person's music", async () => {
    const { api, calls } = fake(() =>
      json({ id: "t9", title: "Dad", created_at: "x", audio_url: "u", mode: "imported" }),
    );
    const song = await api.addRecording(new File(["RIFF"], "dad.wav", { type: "audio/wav" }));
    expect(song).toMatchObject({ id: "t9", title: "Dad", mode: "imported" });
    expect(calls[0]?.path).toBe("/products/wasifyai-voice/tracks/import");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.body).toBeInstanceOf(FormData);
  });

  it("lists the tools' own kinds, each empty where the service does not offer it", async () => {
    const { api } = fake((path) => {
      if (path.includes("wasifyai-notebooks")) return json([{ id: "n1", title: "Plan" }]);
      if (path.includes("wasifyai-model3d")) return json({ detail: "not here" }, 404);
      if (path.includes("builder")) return json({ items: [{ id: "c1", title: "Intro" }] });
      if (path.includes("wasifyai-training")) return json({ models: [] });
      if (path.includes("images")) return json({ images: [], next_before: null });
      if (path.includes("videos")) return json({ videos: [], next_before: null });
      return json({ items: [] });
    });
    const recent = await api.recent();
    expect(recent.others.notebooks.map((n) => n.id)).toEqual(["n1"]);
    expect(recent.others.compositions.map((c) => c.id)).toEqual(["c1"]);
    expect(recent.others.models3d).toEqual([]);
    expect(recent.failed).toEqual([]);
  });
});
