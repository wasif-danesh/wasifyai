import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError, type Transport } from "./transport";
import { createVideoBuilderApi, megabytes } from "./videobuilder";

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

afterEach(() => vi.restoreAllMocks());

describe("the Motion graphics client", () => {
  it("reads the component and sets it up with the size the person was shown", async () => {
    const { transport, calls } = fake(() => json({ installed: false }));
    const api = createVideoBuilderApi(transport);
    await api.component();
    await api.install(287_600_345);
    expect(calls[0]?.path).toBe("/desktop/video-builder");
    expect(calls[1]?.path).toBe("/desktop/video-builder/install");
    expect(calls[1]?.init?.method).toBe("POST");
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({ confirm_bytes: 287_600_345 });
  });

  it("creates, reads, changes and lists projects under the product's builder routes", async () => {
    const project = { id: "a".repeat(32), title: "Hi", slots: {}, renders: [] };
    const { transport, calls } = fake((path) =>
      path.endsWith("/projects") && !path.includes("?")
        ? json({ items: [project] })
        : json(project),
    );
    const api = createVideoBuilderApi(transport);
    expect(await api.list()).toEqual([project]);
    await api.create("title", { title: "Hi", theme: "forest" });
    await api.update(project.id, { title: "Bye" });
    await api.get(project.id);
    const base = "/products/wasifyai-video/builder/projects";
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["GET", base],
      ["POST", base],
      ["PATCH", `${base}/${project.id}`],
      ["GET", `${base}/${project.id}`],
    ]);
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({
      template: "title",
      slots: { title: "Hi", theme: "forest" },
    });
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({ slots: { title: "Bye" } });
  });

  it("creates the other templates by their id and sends rows and lines as they were typed", async () => {
    const { transport, calls } = fake(() => json({ id: "p1" }));
    const api = createVideoBuilderApi(transport);
    await api.create("chart", { title: "Sales", data: "North, 120\nSouth, 95" });
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      template: "chart",
      slots: { title: "Sales", data: "North, 120\nSouth, 95" },
    });
  });

  it("undoes a change, checks the words alone and reads the template catalogue", async () => {
    const { transport, calls } = fake((path) =>
      path.endsWith("/templates")
        ? json({ templates: [{ id: "title" }], shapes: {}, themes: {}, fonts: {} })
        : json({ ok: true, checked: 2, problems: [], message: "Checked." }),
    );
    const api = createVideoBuilderApi(transport);
    expect((await api.templates()).templates[0]?.id).toBe("title");
    await api.undo("p1");
    expect((await api.check("p1")).ok).toBe(true);
    const base = "/products/wasifyai-video/builder";
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["GET", `${base}/templates`],
      ["POST", `${base}/projects/p1/undo`],
      ["POST", `${base}/projects/p1/check`],
    ]);
  });

  it("sends a description, a shape and a CSV file to be drafted, and saves nothing", async () => {
    const reply = {
      template: "chart",
      fields: { title: "Sales" },
      warnings: [],
      summary: "Bar chart",
    };
    const { transport, calls } = fake(() => json(reply));
    const api = createVideoBuilderApi(transport);
    expect(
      await api.draft({
        prompt: "chart it",
        attachment: { name: "s.csv", text: "a,1\nb,2" },
        shape: "portrait",
      }),
    ).toEqual(reply);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.path).toBe("/products/wasifyai-video/builder/draft");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      prompt: "chart it",
      attachment: { name: "s.csv", text: "a,1\nb,2" },
      shape: "portrait",
    });
  });

  it("asks for the file kind a render should be made as", async () => {
    const { transport, calls } = fake(() => json({ id: "r1", status: "working", progress: 0 }));
    const api = createVideoBuilderApi(transport);
    await api.render("p1", "webm");
    await api.render("p1");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ format: "webm" });
    expect(calls[1]?.init?.body).toBeUndefined();
  });

  it("makes a video, follows it and cancels it", async () => {
    const { transport, calls } = fake(() => json({ id: "r1", status: "working", progress: 0.4 }));
    const api = createVideoBuilderApi(transport);
    expect((await api.render("p1")).status).toBe("working");
    expect((await api.renderStatus("r1")).progress).toBe(0.4);
    await api.cancel("r1");
    expect(calls.map((c) => c.path)).toEqual([
      "/products/wasifyai-video/builder/projects/p1/render",
      "/products/wasifyai-video/builder/renders/r1",
      "/products/wasifyai-video/builder/renders/r1/cancel",
    ]);
    expect(calls[2]?.init?.method).toBe("POST");
  });

  it("shows a preview as a picture the window can use", async () => {
    const make = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview-1");
    const { transport, calls } = fake(
      () =>
        new Response(new Uint8Array([137, 80, 78, 71]), {
          headers: { "content-type": "image/png" },
        }),
    );
    const url = await createVideoBuilderApi(transport).preview("p1", 1.5);
    expect(url).toBe("blob:preview-1");
    expect(calls[0]?.path).toBe("/products/wasifyai-video/builder/projects/p1/preview?at=1.5");
    expect(make).toHaveBeenCalledTimes(1);
    await createVideoBuilderApi(transport).preview("p1");
    expect(calls[1]?.path).toBe("/products/wasifyai-video/builder/projects/p1/preview");
  });

  it("says what went wrong in the engine's own words, and tells the app when the session ended", async () => {
    const refused = fake(() =>
      json({ detail: { code: "busy", message: "A video is already being made." } }, 409),
    );
    const err = await createVideoBuilderApi(refused.transport)
      .render("p1")
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect((err as HttpError).status).toBe(409);
    expect((err as HttpError).message).toBe("A video is already being made.");
    const ended = fake(() => json({ detail: "no" }, 401));
    await createVideoBuilderApi(ended.transport)
      .status()
      .catch(() => {});
    expect(ended.unauthorized).toBe(1);
  });

  it("treats a project that is already gone as deleted", async () => {
    const gone = fake(() => json({ detail: "video project not found" }, 404));
    await expect(createVideoBuilderApi(gone.transport).remove("p1")).resolves.toBeUndefined();
    const broken = fake(() => json({ detail: "boom" }, 500));
    await expect(createVideoBuilderApi(broken.transport).remove("p1")).rejects.toBeInstanceOf(
      HttpError,
    );
  });

  it("writes a download size for a person", () => {
    expect(megabytes(287_600_345)).toBe("288 MB");
    expect(megabytes(1_500_000_000)).toBe("1.5 GB");
  });
});
