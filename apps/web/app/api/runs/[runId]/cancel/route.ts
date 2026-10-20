import { badRequest, isUuid, proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

// Stop a run (the chat's Stop button). A run that is already over answers with how it ended.
export async function POST(req: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  if (!isUuid(runId)) return badRequest("invalid run id");
  return proxy(req, `/runs/${runId}/cancel`, { method: "POST" });
}
