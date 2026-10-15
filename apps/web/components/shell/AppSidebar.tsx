"use client";

import { Equaliser } from "@/components/Logo";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { isCurrent, productOf } from "@/lib/nav";
import { PRODUCTS, type Product } from "@/lib/products";
import {
  AudioLines,
  Clapperboard,
  FolderOpen,
  ImageIcon,
  type LucideIcon,
  Mic,
  Music2,
  ShieldCheck,
  Smile,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const ICONS: Record<Product["id"], LucideIcon> = {
  music: Music2,
  image: ImageIcon,
  video: Clapperboard,
  "text-to-speech": AudioLines,
  "speech-to-text": Mic,
  "lip-sync": Smile,
};

/** The side panel inside a product (ADR-0046): the products, the library, admin, and the user's own menu. */
export function AppSidebar({ isAdmin, footer }: { isAdmin: boolean; footer: ReactNode }) {
  const pathname = usePathname();
  const current = productOf(pathname);
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <Link
          href="/"
          aria-label="Wasify AI, home"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 font-semibold outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <Equaliser still />
          <span className="group-data-[collapsible=icon]:hidden">Wasify AI</span>
        </Link>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Create</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {PRODUCTS.map((p) => {
                const Icon = ICONS[p.id];
                const active = current?.id === p.id;
                if (p.status === "soon") {
                  return (
                    <SidebarMenuItem key={p.id}>
                      <SidebarMenuButton
                        asChild
                        tooltip={`${p.title} (coming soon)`}
                        aria-disabled="true"
                        className="opacity-60"
                      >
                        <Link href={p.href}>
                          <Icon aria-hidden="true" />
                          <span>{p.title}</span>
                          <span className="ms-auto text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
                            Soon
                          </span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                }
                return (
                  <SidebarMenuItem key={p.id}>
                    <SidebarMenuButton asChild isActive={active} tooltip={p.title}>
                      <Link href={p.href} aria-current={active ? "page" : undefined}>
                        <Icon aria-hidden="true" />
                        <span>{p.title}</span>
                      </Link>
                    </SidebarMenuButton>
                    {active ? (
                      <SidebarMenuSub aria-label={`${p.title} views`}>
                        {p.views.map((v) => {
                          const here = v.href.includes("?")
                            ? false
                            : pathname === v.href ||
                              (v.href !== p.href && isCurrent(pathname, v.href));
                          return (
                            <SidebarMenuSubItem key={v.href}>
                              <SidebarMenuSubButton asChild isActive={here}>
                                <Link href={v.href}>{v.label}</Link>
                              </SidebarMenuSubButton>
                            </SidebarMenuSubItem>
                          );
                        })}
                      </SidebarMenuSub>
                    ) : null}
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Library</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  asChild
                  isActive={pathname === "/creations"}
                  tooltip="My creations"
                >
                  <Link
                    href="/creations"
                    aria-current={pathname === "/creations" ? "page" : undefined}
                  >
                    <FolderOpen aria-hidden="true" />
                    <span>My creations</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {isAdmin ? (
          <SidebarGroup>
            <SidebarGroupLabel>Admin</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton asChild tooltip="Admin">
                    <Link href="/admin">
                      <ShieldCheck aria-hidden="true" />
                      <span>Admin</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ) : null}
      </SidebarContent>

      <SidebarFooter>{footer}</SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
