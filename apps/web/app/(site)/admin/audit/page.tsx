import { Notice } from "@/components/Notice";
import { AuditTable } from "@/components/admin/tables";
import { TableCell, TableHead, TableRow } from "@/components/ui/table";
import { apiGet } from "@/lib/api";
import { fullDate } from "@/lib/format";
import type { AuditPage } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Audit log" };
export const dynamic = "force-dynamic";

export default async function Audit() {
  let page: AuditPage | null = null;
  try {
    page = await apiGet<AuditPage>("/admin/audit?limit=100");
  } catch {
    // shown below
  }
  if (!page) {
    return (
      <Notice tone="error" title="Couldn't load the audit log">
        The service isn't answering right now.
      </Notice>
    );
  }
  return (
    <AuditTable
      rows={page.entries.map((e) => ({
        id: e.id,
        when: e.created_at ? fullDate(e.created_at) : "—",
        whenAt: e.created_at ?? "",
        who: e.actor_user_id,
        action: e.action,
        detail: JSON.stringify(e.detail ?? {}),
      }))}
    />
  );
}
