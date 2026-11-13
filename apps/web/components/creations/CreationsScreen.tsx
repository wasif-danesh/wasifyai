"use client";

import { webCreationsNav } from "@/lib/creations-nav";
import { webCreations } from "@/lib/library";
import { MyCreations } from "@wasifyai/ui";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

const FILTERS = [
  "songs",
  "images",
  "videos",
  "speeches",
  "transcripts",
  "lipsyncs",
  "models3d",
  "compositions",
  "notebooks",
  "taught",
] as const;

/** The Library: the shared screen (also the desktop's), talking to the BFF, its cards real links. The old
 * "Your images", "Your videos" and "Your music" pages send people here with `show` (ADR-0093, U8). */
export function CreationsScreen({ show, open }: { show?: string; open?: string }) {
  const router = useRouter();
  const nav = useMemo(() => webCreationsNav((href) => router.push(href)), [router]);
  const initialFilter = FILTERS.find((f) => f === show) ?? "all";
  // `open=kind:id`: one entry to open as the Library opens (the home's Recent)
  const at = open?.indexOf(":") ?? -1;
  const initialOpen = open && at > 0 ? { kind: open.slice(0, at), id: open.slice(at + 1) } : null;
  return (
    <MyCreations
      api={webCreations}
      nav={nav}
      initialFilter={initialFilter}
      initialOpen={initialOpen}
      className="grid gap-5"
    />
  );
}
