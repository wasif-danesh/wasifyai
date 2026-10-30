import { badRequest, proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

/** The service's styles, for admins (ADR-0091 S5): the list, a Hugging Face repository's files, a download and its
 * progress, a delete. The API answers 403 to anyone who is not an admin; this only keeps the paths to its shapes. */
const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._~-]{0,79}$/;
const MAX_SEGMENTS = 3;

type Ctx = { params: Promise<{ path?: string[] }> };

async function forward(req: Request, { params }: Ctx) {
  const path = (await params).path ?? [];
  if (path.length > MAX_SEGMENTS || !path.every((s) => SEGMENT.test(s))) {
    return badRequest("invalid path");
  }
  return proxy(req, ["/admin/styles", ...path].join("/"));
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;
