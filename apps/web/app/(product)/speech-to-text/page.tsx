import { Notice } from "@/components/Notice";
import { CreateTranscript } from "@/components/transcribe/CreateTranscript";
import { apiGet } from "@/lib/api";
import type { SpokenLanguages } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Speech to Text" };
export const dynamic = "force-dynamic";

export default async function SpeechToTextPage() {
  let catalog: SpokenLanguages | null = null;
  try {
    catalog = await apiGet<SpokenLanguages>("/products/wasifyai-stt/languages");
  } catch {
    // shown below
  }
  if (!catalog) {
    return (
      <Notice tone="error" title="Couldn't load the languages">
        The service isn't answering right now. Try again in a moment.
      </Notice>
    );
  }
  return <CreateTranscript catalog={catalog} />;
}
