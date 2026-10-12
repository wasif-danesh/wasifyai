import { Notice } from "@/components/Notice";
import { SongsTable } from "@/components/admin/tables";
import { TableCell, TableHead, TableRow } from "@/components/ui/table";
import { TextLink } from "@/components/ui/text-link";
import { apiGet } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { pager } from "@/lib/styles";
import type { AdminSongPage } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Songs" };
export const dynamic = "force-dynamic";

export default async function Songs({
  searchParams,
}: {
  searchParams: Promise<{ before?: string }>;
}) {
  const before = (await searchParams).before;
  const query = before ? `&before=${encodeURIComponent(before)}` : "";
  let page: AdminSongPage | null = null;
  try {
    page = await apiGet<AdminSongPage>(`/admin/songs?limit=25${query}`);
  } catch {
    // shown below
  }
  if (!page) {
    return (
      <Notice tone="error" title="Couldn't load songs">
        The service isn't answering right now.
      </Notice>
    );
  }
  return (
    <>
      <SongsTable
        rows={page.songs.map((s) => ({
          id: s.id,
          title: s.title,
          product: s.product_id,
          user: s.user_email ?? s.user_id,
          made: fullDate(s.created_at),
          madeAt: s.created_at,
        }))}
        footer={
          page.next_before ? (
            <TextLink href={`/admin/songs?before=${encodeURIComponent(page.next_before)}`}>
              Older
            </TextLink>
          ) : null
        }
      />
    </>
  );
}
