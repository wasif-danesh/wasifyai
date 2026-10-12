import { Notice } from "@/components/Notice";
import { CreateLipSync } from "@/components/lipsync/CreateLipSync";
import { apiGet } from "@/lib/api";
import type { VoiceCatalog } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Lip Sync" };
export const dynamic = "force-dynamic";

export default async function LipSyncPage() {
  let catalog: VoiceCatalog | null = null;
  try {
    // a script is spoken by the text to speech voices (ADR-0042)
    catalog = await apiGet<VoiceCatalog>("/products/wasifyai-tts/voices");
  } catch {
    // shown below
  }
  if (!catalog) {
    return (
      <Notice tone="error" title="Couldn't load the voices">
        The service isn't answering right now. Try again in a moment.
      </Notice>
    );
  }
  return <CreateLipSync catalog={catalog} />;
}
