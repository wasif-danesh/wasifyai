import { TranscriptView } from "@/components/transcribe/TranscriptView";
import { ApiError, apiGet } from "@/lib/api";
import { isUuid } from "@/lib/proxy";
import { backLink } from "@/lib/styles";
import type { TranscriptDetail } from "@wasifyai/contracts";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

export const metadata: Metadata = { title: "Transcript" };
export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };

export default async function TranscriptPage({ params }: Props) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  let transcript: TranscriptDetail;
  try {
    transcript = await apiGet<TranscriptDetail>(`/products/wasifyai-stt/transcripts/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  return (
    <>
      <Link href="/creations?show=transcripts" className={backLink}>
        <span aria-hidden="true">←</span> My creations
      </Link>
      <TranscriptView initial={transcript} />
    </>
  );
}
