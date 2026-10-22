import { NavLink } from "@/components/NavLink";
import { Notice } from "@/components/Notice";
import { PageHero } from "@/components/ui/page-hero";
import { apiGet } from "@/lib/api";
import { getMe } from "@/lib/me";
import type { SafeguardsStatus } from "@wasifyai/contracts";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: { default: "Admin", template: "%s · Admin" } };
export const dynamic = "force-dynamic";

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const me = await getMe();
  if (me?.role !== "admin") {
    return (
      <Notice tone="error" title="Admins only">
        You don't have access to this area.
      </Notice>
    );
  }
  const guard = await apiGet<SafeguardsStatus>("/admin/safeguards").catch(() => null);
  return (
    <>
      {guard && !guard.enabled ? (
        <Notice tone="warn" title="Safeguards are off">
          Requests are not moderated and quotas do not apply. Change this under Safeguards.
        </Notice>
      ) : null}
      <div className="grid gap-3">
        <PageHero title="Admin" />
        <nav className="flex flex-wrap gap-1" aria-label="Admin">
          <NavLink href="/admin" exact>
            Overview
          </NavLink>
          <NavLink href="/admin/users">Users</NavLink>
          <NavLink href="/admin/models">Models</NavLink>
          <NavLink href="/admin/media">Media</NavLink>
          <NavLink href="/admin/workers">Workers</NavLink>
          <NavLink href="/admin/safeguards">Safeguards</NavLink>
          <NavLink href="/admin/audit">Audit log</NavLink>
        </nav>
      </div>
      {children}
    </>
  );
}
