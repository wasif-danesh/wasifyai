import { WebModelChoices } from "@/components/models/WebModelChoices";
import { AppSidebar } from "@/components/shell/AppSidebar";
import { UserMenu } from "@/components/shell/UserMenu";
import { WebShell } from "@/components/shell/WebShell";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { getMe } from "@/lib/me";
import { cookies } from "next/headers";
import type { ReactNode } from "react";

/** Everything inside a product gets the side panel (ADR-0046); the home page and sign-in keep the plain header. */
export default async function ProductLayout({ children }: { children: ReactNode }) {
  const store = await cookies();
  const defaultOpen = store.get("sidebar_state")?.value !== "false"; // remembered per browser
  const isAdmin = (await getMe())?.role === "admin";
  return (
    <TooltipProvider>
      <SidebarProvider defaultOpen={defaultOpen}>
        <AppSidebar isAdmin={isAdmin} footer={<UserMenu />} />
        <SidebarInset>
          <WebShell isAdmin={isAdmin}>
            <WebModelChoices isAdmin={isAdmin}>{children}</WebModelChoices>
          </WebShell>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
