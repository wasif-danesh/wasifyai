import { badRequest, proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

/** The engine workers' admin routes (ADR-0087, P5), passed to the API with the signed-in user's identity. The API
 * answers 403 to anyone who is not an admin; this only keeps the paths to the shapes it serves. */
const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._~-]{0,79}$/;
const MAX_SEGMENTS = 4;

type Ctx = { params: Promise<{ path?: string[] }> };

async function forward(req: Request, { params }: Ctx) {
  const path = (await params).path ?? [];
  if (path.length > MAX_SEGMENTS || !path.every((s) => SEGMENT.test(s))) {
    return badRequest("invalid path");
  }
  return proxy(req, ["/admin/workers", ...path].join("/"));
}

export const GET = forward;
export const POST = forward;
