import { Notice } from "@/components/Notice";
import { CreateSpeech } from "@/components/speech/CreateSpeech";
import { apiGet } from "@/lib/api";
import type { VoiceCatalog } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Text to Speech" };
export const dynamic = "force-dynamic";

export default async function TextToSpeechPage() {
  let catalog: VoiceCatalog | null = null;
  try {
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
  return <CreateSpeech catalog={catalog} />;
}
