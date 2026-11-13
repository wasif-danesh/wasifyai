import { proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

/** The styles an admin added for this service, for the image screens (read only, ADR-0091 S5). */
export async function GET(req: Request) {
  return proxy(req, "/styles");
}
