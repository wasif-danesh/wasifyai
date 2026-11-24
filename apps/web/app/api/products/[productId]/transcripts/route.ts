import { badRequest, isProductId, proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

// The API enforces the real limits while it reads; this refuses an obviously too large file early.
const MAX_BYTES = 110 * 1024 * 1024;

type Ctx = { params: Promise<{ productId: string }> };

export async function GET(req: Request, { params }: Ctx) {
  const { productId } = await params;
  if (!isProductId(productId)) return badRequest("invalid product");
  const search = new URL(req.url).search;
  return proxy(req, `/products/${productId}/transcripts${search}`);
}

/** A recording to transcribe, sent as a stream. This route shadows the catch-all for every method, so a
 * method left out here answers 405 instead of reaching the API. */
export async function POST(req: Request, { params }: Ctx) {
  const { productId } = await params;
  if (!isProductId(productId)) return badRequest("invalid product");
  const declared = Number(req.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_BYTES) {
    return Response.json({ detail: "That file is too large." }, { status: 413 });
  }
  return proxy(req, `/products/${productId}/transcripts`, {
    body: req.body,
    headers: { "content-type": req.headers.get("content-type") ?? "application/octet-stream" },
  });
}
