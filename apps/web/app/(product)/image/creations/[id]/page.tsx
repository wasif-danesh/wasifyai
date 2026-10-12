import { ImageView } from "@/components/image/ImageView";
import { ApiError, apiGet } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { isUuid } from "@/lib/proxy";
import { backLink } from "@/lib/styles";
import type { ImageSummary } from "@wasifyai/contracts";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

export const metadata: Metadata = { title: "Image" };
export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };

export default async function ImageDetail({ params }: Props) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  let image: ImageSummary;
  try {
    image = await apiGet<ImageSummary>(`/products/wasifyai-image/images/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  return (
    <>
      <Link href="/creations" className={backLink}>
        <span aria-hidden="true">←</span> My creations
      </Link>
      <ImageView image={image} when={fullDate(image.created_at)} />
    </>
  );
}
