import { proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

/** The models this service uses for chat, images and video, for the "Select ... model" button (read only). */
export async function GET(req: Request) {
  return proxy(req, "/models/in-use");
}
