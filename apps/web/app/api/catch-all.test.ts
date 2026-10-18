import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DELETE, GET, PATCH, POST } from "./products/[productId]/[...path]/route";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const ctx = (productId: string, path: string[]) => ({
  params: Promise.resolve({ productId, path }),
});
const upstreamUrl = () => fetchMock.mock.calls.at(-1)?.[0] as string;
const upstreamInit = () => fetchMock.mock.calls.at(-1)?.[1] as RequestInit;

describe("any other product route", () => {
  it("passes a read through with its query string", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ items: [] }));
    const res = await GET(
      new Request("http://web/x?limit=5&before=2026-01-01"),
      ctx("wasifyai-voice", ["tracks"]),
    );
    expect(res.status).toBe(200);
    expect(upstreamUrl()).toMatch(/\/products\/wasifyai-voice\/tracks\?limit=5&before=2026-01-01$/);
  });

  it("passes a JSON change through to a nested route", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ id: "a", favourite: true }));
    await PATCH(
      new Request("http://web/x", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ favourite: true }),
      }),
      ctx("wasifyai-image", ["images", "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80"]),
    );
    expect(upstreamUrl()).toMatch(
      /\/products\/wasifyai-image\/images\/0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80$/,
    );
    expect(upstreamInit().method).toBe("PATCH");
    expect(new Headers(upstreamInit().headers).get("content-type")).toBe("application/json");
  });

  it("streams a body with its content type and passes a delete", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await POST(
      new Request("http://web/x", {
        method: "POST",
        headers: { "content-type": "audio/wav" },
        body: new Uint8Array([1, 2, 3]),
      }),
      ctx("wasifyai-voice", ["tracks", "import"]),
    );
    expect(new Headers(upstreamInit().headers).get("content-type")).toBe("audio/wav");
    const gone = await DELETE(
      new Request("http://web/x", { method: "DELETE" }),
      ctx("wasifyai-voice", ["clips", "c1"]),
    );
    expect(gone.status).toBe(204);
    expect(upstreamUrl()).toMatch(/\/products\/wasifyai-voice\/clips\/c1$/);
  });

  it("refuses an obviously huge body before calling the API", async () => {
    const res = await POST(
      new Request("http://web/x", {
        method: "POST",
        headers: { "content-length": String(200 * 1024 * 1024) },
        body: "x",
      }),
      ctx("wasifyai-voice", ["tracks", "import"]),
    );
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("only forwards paths of plain segments, to a real product id, and never a run", async () => {
    for (const [product, path] of [
      ["Bad Product", ["tracks"]],
      ["wasifyai-voice", []],
      ["wasifyai-voice", [".."]],
      ["wasifyai-voice", ["tracks", "..", "admin"]],
      ["wasifyai-voice", ["a%2Fb"]],
      ["wasifyai-voice", ["a", "b", "c", "d", "e", "f", "g"]],
      ["wasifyai-voice", ["runs"]],
    ] as const) {
      const res = await GET(new Request("http://web/x"), ctx(product, [...path]));
      expect(res.status, `${product}/${path.join("/")}`).toBe(400);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
