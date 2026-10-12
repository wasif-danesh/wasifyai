import { LipSyncView } from "@/components/lipsync/LipSyncView";
import { ApiError, apiGet } from "@/lib/api";
import { isUuid } from "@/lib/proxy";
import { backLink } from "@/lib/styles";
import type { LipSyncSummary } from "@wasifyai/contracts";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

export const metadata: Metadata = { title: "Lip Sync" };
export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };

export default async function LipSyncDetail({ params }: Props) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  let lipsync: LipSyncSummary;
  try {
    lipsync = await apiGet<LipSyncSummary>(`/products/wasifyai-lipsync/lipsyncs/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  return (
    <>
      <Link href="/creations" className={backLink}>
        <span aria-hidden="true">←</span> My creations
      </Link>
      <LipSyncView initial={lipsync} />
    </>
  );
}
