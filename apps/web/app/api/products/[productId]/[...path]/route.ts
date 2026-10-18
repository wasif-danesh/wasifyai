import { badRequest, isProductId, proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

/** Any other route an engine product serves under `/products/{id}/...`, passed through to the API with the
 * signed-in user's identity. The routes with their own handlers (runs, uploads, downloads, listings) are matched
 * first by Next.js; this one means a new engine route needs no web code. */

// the largest body let through; the API enforces the real limits while it reads
const MAX_BYTES = 110 * 1024 * 1024;
const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._~-]{0,79}$/;
const MAX_SEGMENTS = 6;

type Ctx = { params: Promise<{ productId: string; path: string[] }> };

async function forward(req: Request, { params }: Ctx) {
  const { productId, path } = await params;
  if (!isProductId(productId)) return badRequest("invalid product");
  if (path.length === 0 || path.length > MAX_SEGMENTS || !path.every((s) => SEGMENT.test(s))) {
    return badRequest("invalid path");
  }
  // runs are started and followed by their own handlers, which keep the event streams intact
  if (path[0] === "runs") return badRequest("invalid path");
  const search = new URL(req.url).search;
  const target = `/products/${productId}/${path.join("/")}${search}`;
  if (req.method === "GET" || req.method === "DELETE") return proxy(req, target);
  const declared = Number(req.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_BYTES) {
    return Response.json({ detail: "That file is too large." }, { status: 413 });
  }
  return proxy(req, target, {
    body: req.body,
    headers: { "content-type": req.headers.get("content-type") ?? "application/octet-stream" },
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
