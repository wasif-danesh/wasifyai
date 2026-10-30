import { NavLink } from "@/components/NavLink";
import { Notice } from "@/components/Notice";
import { PageHero } from "@/components/ui/page-hero";
import { getMe } from "@/lib/me";
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
  return (
    <>
      <div className="grid gap-3">
        <PageHero title="Admin" />
        <nav className="flex flex-wrap gap-1" aria-label="Admin">
          <NavLink href="/admin" exact>
            Overview
          </NavLink>
          <NavLink href="/admin/users">Users</NavLink>
          <NavLink href="/admin/models">Models</NavLink>
          <NavLink href="/admin/media">Media</NavLink>
          <NavLink href="/admin/styles">Styles</NavLink>
          <NavLink href="/admin/workers">Models and workers</NavLink>
          <NavLink href="/admin/search">Search</NavLink>
          <NavLink href="/admin/settings">Settings</NavLink>
          <NavLink href="/admin/audit">Audit log</NavLink>
        </nav>
      </div>
      {children}
    </>
  );
}
