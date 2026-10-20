import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RUN, sse } from "../../test-utils";
import { GET as searchGET } from "./creations/search/route";
import { GET as imageDownloadGET } from "./products/[productId]/images/[imageId]/download/route";
import {
  DELETE as imageDELETE,
  GET as imageGET,
} from "./products/[productId]/images/[imageId]/route";
import { POST as enhancePOST } from "./products/[productId]/prompt/enhance/route";
import { POST as runsPOST } from "./products/[productId]/runs/route";
import { DELETE as uploadDELETE } from "./products/[productId]/uploads/images/[uploadId]/route";
import { POST as uploadPOST } from "./products/[productId]/uploads/images/route";
import { GET as videoDownloadGET } from "./products/[productId]/videos/[videoId]/download/route";
import {
  DELETE as videoDELETE,
  GET as videoGET,
} from "./products/[productId]/videos/[videoId]/route";
import { GET as videosGET } from "./products/[productId]/videos/route";
import { POST as cancelPOST } from "./runs/[runId]/cancel/route";
import { GET as eventsGET } from "./runs/[runId]/events/route";
import { POST as resumePOST } from "./runs/[runId]/resume/route";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const params = <T extends object>(p: T) => ({ params: Promise.resolve(p) });
const upstreamUrl = () => fetchMock.mock.calls.at(-1)?.[0] as string;
const upstreamInit = () => fetchMock.mock.calls.at(-1)?.[1] as RequestInit;

describe("without a session", () => {
  afterEach(() => {
    process.env.AUTH_MODE = "stub";
    vi.doUnmock("@/auth");
    vi.resetModules();
  });

  it("answers 401 and never calls the API", async () => {
    process.env.AUTH_MODE = "jwt";
    vi.doMock("@/auth", () => ({ auth: async () => null }));
    const { GET } = await import("./products/[productId]/videos/route");
    const res = await GET(
      new Request("http://web/api/products/wasifyai-video/videos"),
      params({ productId: "wasifyai-video" }),
    );
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("start a run", () => {
  it("forwards the body to the API and streams the events back unchanged", async () => {
    fetchMock.mockResolvedValueOnce(sse([["token", { node: "write_lyrics", text: "hi" }]]));
    const res = await runsPOST(
      new Request("http://web/api/products/wasifyai-music/runs", {
        method: "POST",
        body: '{"input":{"idea":"x"}}',
      }),
      params({ productId: "wasifyai-music" }),
    );
    expect(upstreamUrl()).toMatch(/\/products\/wasifyai-music\/runs$/);
    expect(upstreamInit().method).toBe("POST");
    expect(upstreamInit().body).toBe('{"input":{"idea":"x"}}');
    expect(res.headers.get("content-type")).toMatch(/text\/event-stream/);
    expect(res.headers.get("cache-control")).toBe("no-cache, no-transform"); // no buffering on the way
    expect(await res.text()).toContain("event: token");
  });

  it.each(["../admin", "A B", "wasifyai music", "", "x".repeat(80)])(
    "rejects the product id %j before calling the API",
    async (id) => {
      const res = await runsPOST(
        new Request("http://web/x", { method: "POST", body: "{}" }),
        params({ productId: id }),
      );
      expect(res.status).toBe(400);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("passes the API's error status and message through", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "unknown product" }, { status: 404 }));
    const res = await runsPOST(
      new Request("http://web/x", { method: "POST", body: "{}" }),
      params({ productId: "nope" }),
    );
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ detail: "unknown product" });
  });
});

describe("answer a run", () => {
  it("forwards the answer to that run", async () => {
    fetchMock.mockResolvedValueOnce(sse([]));
    await resumePOST(
      new Request("http://web/x", { method: "POST", body: '{"value":{"action":"approve"}}' }),
      params({ runId: RUN }),
    );
    expect(upstreamUrl()).toMatch(new RegExp(`/runs/${RUN}/resume$`));
    expect(upstreamInit().body).toBe('{"value":{"action":"approve"}}');
  });

  it("only accepts real run ids", async () => {
    const res = await resumePOST(
      new Request("http://web/x", { method: "POST", body: "{}" }),
      params({ runId: "../../health" }),
    );
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("stop a run", () => {
  it("asks the API to stop that run", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ run_id: RUN, status: "cancelled" }));
    const res = await cancelPOST(
      new Request("http://web/x", { method: "POST" }),
      params({ runId: RUN }),
    );
    expect(res.status).toBe(200);
    expect(upstreamUrl()).toMatch(new RegExp(`/runs/${RUN}/cancel$`));
    expect(upstreamInit().method).toBe("POST");
  });

  it("only accepts real run ids", async () => {
    const res = await cancelPOST(
      new Request("http://web/x", { method: "POST" }),
      params({ runId: "../../health" }),
    );
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("reconnect to a run", () => {
  const call = (headers: Record<string, string>, runId = RUN) =>
    eventsGET(new Request("http://web/x", { headers }), params({ runId }));

  it("passes Last-Event-ID so the server replays only what was missed", async () => {
    fetchMock.mockResolvedValueOnce(sse([]));
    await call({ "last-event-id": "42" });
    expect((upstreamInit().headers as Record<string, string>)["last-event-id"]).toBe("42");
  });

  it.each(["abc", "12abc", "-1", "1; drop", " "])(
    "drops a Last-Event-ID that is not a plain number (%j)",
    async (bad) => {
      fetchMock.mockResolvedValueOnce(sse([]));
      await call({ "last-event-id": bad });
      expect(upstreamInit().headers as Record<string, string>).not.toHaveProperty("last-event-id");
    },
  );

  it("only accepts real run ids", async () => {
    expect((await call({}, "not-a-uuid")).status).toBe(400);
  });
});

describe("images and uploads", () => {
  it("streams an upload to the API with its content type", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ key: "k", id: "1" }));
    const res = await uploadPOST(
      new Request("http://web/x", {
        method: "POST",
        headers: { "content-type": "image/png" },
        body: new Uint8Array([1, 2, 3]),
      }),
      params({ productId: "wasifyai-image" }),
    );
    expect(res.status).toBe(200);
    expect(upstreamUrl()).toMatch(/\/products\/wasifyai-image\/uploads\/images$/);
    expect(new Headers(upstreamInit().headers).get("content-type")).toBe("image/png");
  });

  it("refuses an obviously huge upload before calling the API", async () => {
    const res = await uploadPOST(
      new Request("http://web/x", {
        method: "POST",
        headers: { "content-length": String(100 * 1024 * 1024) },
        body: "x",
      }),
      params({ productId: "wasifyai-image" }),
    );
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("gets and deletes an image by id and refuses ids that are not UUIDs", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ id: RUN }));
    await imageGET(
      new Request("http://web/x"),
      params({ productId: "wasifyai-image", imageId: RUN }),
    );
    expect(upstreamUrl()).toMatch(new RegExp(`/images/${RUN}$`));
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await imageDELETE(
      new Request("http://web/x", { method: "DELETE" }),
      params({ productId: "wasifyai-image", imageId: RUN }),
    );
    expect(upstreamInit().method).toBe("DELETE");
    const bad = await imageGET(
      new Request("http://web/x"),
      params({ productId: "wasifyai-image", imageId: "../x" }),
    );
    expect(bad.status).toBe(400);
  });

  it("passes the image download through as an attachment", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("PNG", {
        headers: {
          "content-type": "image/png",
          "content-disposition": 'attachment; filename="a.png"',
        },
      }),
    );
    const res = await imageDownloadGET(
      new Request("http://web/x"),
      params({ productId: "wasifyai-image", imageId: RUN }),
    );
    expect(res.headers.get("content-disposition")).toBe('attachment; filename="a.png"');
    expect(await res.text()).toBe("PNG");
  });

  it("takes back an upload by id and refuses ids that are not UUIDs", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const res = await uploadDELETE(
      new Request("http://web/x", { method: "DELETE" }),
      params({ productId: "wasifyai-image", uploadId: RUN }),
    );
    expect(res.status).toBe(204);
    expect(upstreamUrl()).toMatch(new RegExp(`/uploads/images/${RUN}$`));
    expect(upstreamInit().method).toBe("DELETE");
    const bad = await uploadDELETE(
      new Request("http://web/x", { method: "DELETE" }),
      params({ productId: "wasifyai-image", uploadId: "../x" }),
    );
    expect(bad.status).toBe(400);
  });

  it("passes a prompt to enhance through as JSON", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ prompt: "A fox.", changed: true }));
    const res = await enhancePOST(
      new Request("http://web/x", {
        method: "POST",
        body: JSON.stringify({ kind: "text_to_image", prompt: "fox", upload_id: null }),
      }),
      params({ productId: "wasifyai-image" }),
    );
    expect(await res.json()).toEqual({ prompt: "A fox.", changed: true });
    expect(upstreamUrl()).toMatch(/\/products\/wasifyai-image\/prompt\/enhance$/);
    expect(JSON.parse(upstreamInit().body as string).kind).toBe("text_to_image");
    const huge = await enhancePOST(
      new Request("http://web/x", { method: "POST", body: "x".repeat(30_000) }),
      params({ productId: "wasifyai-image" }),
    );
    expect(huge.status).toBe(400);
  });

  it("lists clips with their paging and status filter, gets and deletes one, and downloads it", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ videos: [], next_before: null }));
    await videosGET(
      new Request("http://web/x?status=working&limit=5"),
      params({ productId: "wasifyai-video" }),
    );
    expect(upstreamUrl()).toMatch(/\/products\/wasifyai-video\/videos\?status=working&limit=5$/);
    fetchMock.mockResolvedValueOnce(Response.json({ id: RUN }));
    await videoGET(
      new Request("http://web/x"),
      params({ productId: "wasifyai-video", videoId: RUN }),
    );
    expect(upstreamUrl()).toMatch(new RegExp(`/videos/${RUN}$`));
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await videoDELETE(
      new Request("http://web/x", { method: "DELETE" }),
      params({ productId: "wasifyai-video", videoId: RUN }),
    );
    expect(upstreamInit().method).toBe("DELETE");
    fetchMock.mockResolvedValueOnce(
      new Response("MP4", {
        headers: {
          "content-type": "video/mp4",
          "content-disposition": 'attachment; filename="a.mp4"',
        },
      }),
    );
    const res = await videoDownloadGET(
      new Request("http://web/x"),
      params({ productId: "wasifyai-video", videoId: RUN }),
    );
    expect(res.headers.get("content-disposition")).toBe('attachment; filename="a.mp4"');
    expect(upstreamUrl()).toMatch(/\/download$/);
    const bad = await videoGET(
      new Request("http://web/x"),
      params({ productId: "wasifyai-video", videoId: "../x" }),
    );
    expect(bad.status).toBe(400);
  });

  it("passes a search through with its query string", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ query: "fox", degraded: false, results: [] }));
    const res = await searchGET(
      new Request("http://web/api/creations/search?q=fox&kind=song&limit=5"),
    );
    expect(await res.json()).toMatchObject({ query: "fox" });
    expect(upstreamUrl()).toMatch(/\/creations\/search\?q=fox&kind=song&limit=5$/);
  });
});
