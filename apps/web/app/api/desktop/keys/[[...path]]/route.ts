import { badRequest, proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

/** The service's media keys and each product's cloud model (ADR-0100, CP11), passed to the API with the signed-in
 * user's identity. The API answers 403 to anyone who is not an admin; this only keeps the paths to the shapes it
 * serves (`/desktop/keys`, `/<product>/cloud`, `/<product>/use`, `/<product>/keys/<provider>[/test|/check]`). */
const SEGMENT = /^[a-z0-9][a-z0-9._-]{0,79}$/;
const MAX_SEGMENTS = 4;

type Ctx = { params: Promise<{ path?: string[] }> };

async function forward(req: Request, { params }: Ctx) {
  const path = (await params).path ?? [];
  if (path.length > MAX_SEGMENTS || !path.every((s) => SEGMENT.test(s))) {
    return badRequest("invalid path");
  }
  const body = req.method === "PUT" || req.method === "POST" ? await req.text() : undefined;
  return proxy(req, ["/desktop/keys", ...path].join("/"), {
    ...(body ? { body, headers: { "content-type": "application/json" } } : {}),
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const DELETE = forward;
