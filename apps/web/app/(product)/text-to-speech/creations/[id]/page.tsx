import { SpeechView } from "@/components/speech/SpeechView";
import { ApiError, apiGet } from "@/lib/api";
import { isUuid } from "@/lib/proxy";
import { backLink } from "@/lib/styles";
import type { SpeechSummary } from "@wasifyai/contracts";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

export const metadata: Metadata = { title: "Speech" };
export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };

export default async function SpeechDetail({ params }: Props) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  let speech: SpeechSummary;
  try {
    speech = await apiGet<SpeechSummary>(`/products/wasifyai-tts/speeches/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  return (
    <>
      <Link href="/creations" className={backLink}>
        <span aria-hidden="true">←</span> My creations
      </Link>
      <SpeechView speech={speech} />
    </>
  );
}
