"use client";

import { Activity } from "@/components/shell/Activity";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useVideoActivity } from "@/hooks/use-video-activity";
import { useVoiceOffer } from "@/hooks/use-voice-offer";
import { hrefOf } from "@/lib/creations-nav";
import { webCreations } from "@/lib/library";
import { resolveWebItem } from "@/lib/menu";
import { crumbs } from "@/lib/nav";
import { page } from "@/lib/styles";
import {
  AppBar,
  JobTray,
  type Place,
  SearchPalette,
  type TrayJob,
  type WindowBar,
  WindowBarProvider,
  placesOf,
  titleOf,
} from "@wasifyai/ui";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useCallback, useMemo, useState } from "react";

/**
 * The web's half of the one shell (ADR-0093, stage U2): the same `AppBar` as the desktop window above every
 * product page, with the title and tabs of where the person is, the job tray, search (⌘K) and the theme; the
 * screens put their model button into the bar through `PageHeader`.
 */
export function WebShell({ isAdmin, children }: { isAdmin: boolean; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const show = useSearchParams()?.get("show") ?? null;
  const voiceScreens = useVoiceOffer();
  const resolve = useMemo(
    () => resolveWebItem(pathname, show, { voiceScreens, isAdmin }),
    [pathname, show, voiceScreens, isAdmin],
  );
  const title = titleOf(resolve) ?? crumbs(pathname).at(-1)?.label ?? pageTitle(pathname);

  // the bar's slot, where a screen's header goes, and whether one has taken the title
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const [claims, setClaims] = useState(0);
  const bar = useMemo<WindowBar | null>(
    () =>
      slot
        ? {
            target: slot,
            claim: () => {
              setClaims((n) => n + 1);
              return () => setClaims((n) => n - 1);
            },
          }
        : null,
    [slot],
  );

  // the clips being made, in the tray (the engine's job list is the desktop's; the web asks its own lists)
  const video = useVideoActivity(true);
  const working = video.working;
  const load = useCallback(
    async (): Promise<TrayJob[]> =>
      working.map((v) => ({ id: v.id, label: `Making your video: ${v.prompt}` })),
    [working],
  );

  const [searching, setSearching] = useState(false);
  const openSearch = useCallback(() => setSearching(true), []);
  const places = useMemo<Place[]>(
    () =>
      placesOf(resolve).flatMap((p) => {
        const href = p.view.href;
        return href ? [{ id: p.id, label: p.label, onSelect: () => router.push(href) }] : [];
      }),
    [resolve, router],
  );

  return (
    <WindowBarProvider bar={bar}>
      <AppBar
        nav={<SidebarTrigger aria-label="Show or hide the side panel" className="ms-2 shrink-0" />}
        title={title}
        showTitle={claims === 0}
        slot={setSlot}
        tray={<JobTray load={load} />}
        onSearch={openSearch}
        className="sticky top-0 z-20 bg-background/90 backdrop-blur"
      />
      <main id="main" className={page}>
        {children}
      </main>
      <SearchPalette
        open={searching}
        onClose={() => setSearching(false)}
        places={places}
        creations={webCreations}
        onOpenCreation={(entry) => router.push(hrefOf(entry))}
      />
      <Activity activity={video} />
    </WindowBarProvider>
  );
}

/** A title for a page the menu does not name. */
function pageTitle(pathname: string): string {
  if (pathname === "/design") return "Design";
  if (pathname.startsWith("/admin")) return "Admin";
  return "Wasify AI";
}
