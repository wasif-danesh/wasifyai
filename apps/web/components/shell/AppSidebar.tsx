"use client";

import { Sidebar, SidebarContent, SidebarRail } from "@/components/ui/sidebar";
import { useVoiceOffer } from "@/hooks/use-voice-offer";
import { webAssistant } from "@/lib/library";
import { resolveWebItem } from "@/lib/menu";
import { SideMenu, conversationsChanged, useConversations } from "@wasifyai/ui";
import { Compass, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

/** The side panel inside a product (ADR-0046): the same menu as the desktop window (packages/ui), with what
 * each item opens on the web, an Admin link for admins, and the user's own menu at the bottom. */
export function AppSidebar({
  isAdmin,
  footer,
}: {
  isAdmin: boolean;
  footer: ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const show = useSearchParams()?.get("show") ?? null;
  const chats = useConversations(webAssistant);
  const voiceScreens = useVoiceOffer();
  const chatId = /^\/chat\/([\w-]+)$/.exec(pathname)?.[1];
  return (
    <Sidebar collapsible="offcanvas">
      <SidebarContent className="gap-0 overflow-hidden">
        <SideMenu
          resolve={resolveWebItem(pathname, show, { voiceScreens, isAdmin })}
          link={Link}
          brandHref="/"
          recents={{
            items: chats.map((c) => ({
              id: c.id,
              title: c.title,
              current: chatId === c.id,
              onSelect: () => router.push(`/chat/${c.id}`),
              rename: async (name: string) => {
                await webAssistant.rename(c.id, name);
                conversationsChanged();
              },
              remove: async () => {
                await webAssistant.remove(c.id);
                conversationsChanged();
                if (chatId === c.id) router.push("/"); // the chat on the screen is gone: a new one
              },
            })),
          }}
          extra={[
            { id: "explore", label: "Explore", icon: Compass, href: "/explore" },
            ...(isAdmin
              ? [
                  {
                    id: "admin",
                    label: "Admin",
                    icon: ShieldCheck,
                    href: "/admin",
                    current: pathname.startsWith("/admin"),
                  },
                ]
              : []),
          ]}
          footer={footer}
        />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  );
}
