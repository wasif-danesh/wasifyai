import { VideoView } from "@/components/video/VideoView";
import { ApiError, apiGet } from "@/lib/api";
import { isUuid } from "@/lib/proxy";
import { backLink } from "@/lib/styles";
import type { VideoSummary } from "@wasifyai/contracts";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

export const metadata: Metadata = { title: "Video" };
export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };

export default async function VideoDetail({ params }: Props) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  let video: VideoSummary;
  try {
    video = await apiGet<VideoSummary>(`/products/wasifyai-video/videos/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  return (
    <>
      <Link href="/creations" className={backLink}>
        <span aria-hidden="true">←</span> My creations
      </Link>
      <VideoView initial={video} />
    </>
  );
}
