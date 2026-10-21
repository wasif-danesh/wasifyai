import { AppSidebar } from "@/components/shell/AppSidebar";
import { TopBar } from "@/components/shell/TopBar";
import { UserMenu } from "@/components/shell/UserMenu";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { getMe } from "@/lib/me";
import { page } from "@/lib/styles";
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
          <TopBar />
          <main id="main" className={page}>
            {children}
          </main>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
