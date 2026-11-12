import { badRequest, isProductId, proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

// The API enforces the real limits while it reads (a recording 50 MB, a clip 200 MB); this refuses an obviously
// too large file early.
const MAX_BYTES = 210 * 1024 * 1024;

/** A recording or a clip attached in the chat (docs/chat-does-everything-plan.md, CE2), passed through to the API as
 * a stream with its name, whose extension says which it is. */
export async function POST(req: Request, { params }: { params: Promise<{ productId: string }> }) {
  const { productId } = await params;
  if (!isProductId(productId)) return badRequest("invalid product");
  const declared = Number(req.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_BYTES) {
    return Response.json(
      { detail: "That file is too large. The limit is 200 MB." },
      { status: 413 },
    );
  }
  const name = req.headers.get("x-file-name");
  return proxy(req, `/products/${productId}/attachments/media`, {
    body: req.body,
    headers: {
      "content-type": req.headers.get("content-type") ?? "application/octet-stream",
      ...(name ? { "x-file-name": name } : {}),
    },
  });
}
