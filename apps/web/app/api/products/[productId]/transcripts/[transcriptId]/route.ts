import { badRequest, isProductId, isUuid, proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ productId: string; transcriptId: string }> };

async function forward(req: Request, { params }: Ctx) {
  const { productId, transcriptId } = await params;
  if (!isProductId(productId) || !isUuid(transcriptId)) return badRequest("invalid id");
  const target = `/products/${productId}/transcripts/${transcriptId}`;
  if (req.method !== "PATCH") return proxy(req, target);
  // a rename; this route shadows the catch-all, so a method left out here answers 405
  return proxy(req, target, { body: req.body, headers: { "content-type": "application/json" } });
}

export const GET = forward;
export const PATCH = forward;
export const DELETE = forward;
