import { Notice } from "@/components/Notice";
import { UsersTable } from "@/components/admin/tables";
import { TableCell, TableHead, TableRow } from "@/components/ui/table";
import { TextLink } from "@/components/ui/text-link";
import { apiGet } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { muted, pager } from "@/lib/styles";
import type { AdminUserPage } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Users" };
export const dynamic = "force-dynamic";

export default async function Users({
  searchParams,
}: {
  searchParams: Promise<{ before?: string }>;
}) {
  const before = (await searchParams).before;
  const query = before ? `&before=${encodeURIComponent(before)}` : "";
  let page: AdminUserPage | null = null;
  try {
    page = await apiGet<AdminUserPage>(`/admin/users?limit=25${query}`);
  } catch {
    // shown below
  }
  if (!page) {
    return (
      <Notice tone="error" title="Couldn't load users">
        The service isn't answering right now.
      </Notice>
    );
  }
  return (
    <>
      <UsersTable
        rows={page.users.map((u) => ({
          id: u.id,
          name: u.name ?? "—",
          email: u.email ?? "—",
          unverified: Boolean(u.email && !u.email_verified),
          role: u.role,
          providers: u.providers.join(", "),
          joined: fullDate(u.created_at),
          joinedAt: u.created_at,
        }))}
        footer={
          page.next_before ? (
            <TextLink href={`/admin/users?before=${encodeURIComponent(page.next_before)}`}>
              Older
            </TextLink>
          ) : null
        }
      />
    </>
  );
}
