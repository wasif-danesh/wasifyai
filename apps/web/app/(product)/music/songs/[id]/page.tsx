import { SongView } from "@/components/SongView";
import { ApiError, apiGet } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { isUuid } from "@/lib/proxy";
import { PRODUCT } from "@/lib/run-client";
import { backLink } from "@/lib/styles";
import type { SongDetail } from "@wasifyai/contracts";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };

async function load(id: string): Promise<SongDetail> {
  if (!isUuid(id)) notFound();
  try {
    return await apiGet<SongDetail>(`/products/${PRODUCT}/songs/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  try {
    return { title: (await load(id)).title };
  } catch {
    return { title: "Song" };
  }
}

export default async function SongPage({ params }: Props) {
  const { id } = await params;
  const song = await load(id);
  return (
    <>
      <Link href="/creations" className={backLink}>
        <span aria-hidden="true">←</span> My creations
      </Link>
      <SongView
        heading="h1"
        song={{
          songId: song.id,
          title: song.title,
          style: song.style,
          lyrics: song.lyrics,
          audioUrl: song.audio_url,
          coverUrl: song.cover_url ?? null,
          when: fullDate(song.created_at),
        }}
      />
    </>
  );
}
