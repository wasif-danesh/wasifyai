import { describe, expect, it } from "vitest";
import { canRunAgain, createImagesApi, sizeName, when } from "./images";
import { HttpError, type Transport } from "./transport";

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

describe("images api", () => {
  it("lists with a limit, a cursor and the favourites filter", async () => {
    const { transport, calls } = fake({
      "/products/wasifyai-image/images": () => json({ images: [], next_before: null }),
    });
    await createImagesApi(transport).list({
      limit: 10,
      before: "2026-10-01T00:00:00Z",
      favourites: true,
    });
    expect(calls[0].path).toBe(
      "/products/wasifyai-image/images?limit=10&before=2026-10-01T00%3A00%3A00Z&favourites=true",
    );
  });

  it("turns search results into the cards, in the order found", async () => {
    const { transport, calls } = fake({
      "/creations/search": () => json({ results: [{ id: "b" }, { id: "a" }] }),
      "/products/wasifyai-image/images?ids=": () => json({ images: [{ id: "b" }, { id: "a" }] }),
    });
    const found = await createImagesApi(transport).search("a fox");
    expect(found.map((i) => i.id)).toEqual(["b", "a"]);
    expect(calls[0].path).toBe("/creations/search?q=a+fox&kind=image&limit=24");
    expect(calls[1].path).toBe("/products/wasifyai-image/images?ids=b,a");
  });

  it("asks nothing more when nothing matched", async () => {
    const { transport, calls } = fake({ "/creations/search": () => json({ results: [] }) });
    expect(await createImagesApi(transport).search("zzz")).toEqual([]);
    expect(calls).toHaveLength(1);
  });

  it("patches the favourite flag and posts an export", async () => {
    const { transport, calls } = fake({
      "/products/wasifyai-image/images/i1/export": () => json({ name: "a.png", path: "/d/a.png" }),
      "/products/wasifyai-image/images/i1": () => json({ id: "i1", favourite: true }),
    });
    const api = createImagesApi(transport);
    expect((await api.setFavourite("i1", true)).favourite).toBe(true);
    expect(calls[0].init?.method).toBe("PATCH");
    expect(calls[0].init?.body).toBe('{"favourite":true}');
    expect(await api.exportCopy("i1")).toEqual({ name: "a.png", path: "/d/a.png" });
    expect(calls[1].init?.method).toBe("POST");
  });

  it("treats an image that is already gone as deleted, and reports other failures", async () => {
    const gone = fake({ "/products/": () => new Response(null, { status: 404 }) });
    await expect(createImagesApi(gone.transport).remove("x")).resolves.toBeUndefined();
    const broken = fake({ "/products/": () => json({ detail: "disk full" }, 500) });
    await expect(createImagesApi(broken.transport).remove("x")).rejects.toThrow(HttpError);
  });

  it("reads the engine's own message from an error", async () => {
    const { transport } = fake({
      "/products/": () => json({ detail: "saving is not available" }, 404),
    });
    await expect(createImagesApi(transport).exportCopy("i1")).rejects.toMatchObject({
      status: 404,
      message: "saving is not available",
    });
  });
});

describe("helpers", () => {
  it("names the common shapes", () => {
    expect(sizeName(1024, 1024)).toBe("Square 1:1");
    expect(sizeName(1152, 864)).toBe("Landscape 4:3");
    expect(sizeName(864, 1152)).toBe("Portrait 3:4");
    expect(sizeName(1344, 756)).toBe("Wide 16:9");
    expect(sizeName(756, 1344)).toBe("Tall 9:16");
    expect(sizeName(1000, 300)).toBe("1000×300");
  });

  it("says today and yesterday in words", () => {
    const now = new Date("2026-10-15T15:00:00");
    expect(when("2026-10-15T08:00:00", now)).toBe("Today");
    expect(when("2026-10-14T20:00:00", now)).toBe("Yesterday");
  });

  it("offers run again only for a text image with a recipe", () => {
    const recipe = {
      v: 1,
      mode: "text",
      prompt: "p",
      size: "wide",
      width: 1,
      height: 1,
      seed: 5,
    } as const;
    expect(canRunAgain({ mode: "text", recipe })).toBe(true);
    expect(canRunAgain({ mode: "text", recipe: null })).toBe(false);
    expect(canRunAgain({ mode: "image", recipe: { ...recipe, mode: "image", size: null } })).toBe(
      false,
    );
  });
});
