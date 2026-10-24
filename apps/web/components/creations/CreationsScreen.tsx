"use client";

import { webCreationsNav } from "@/lib/creations-nav";
import { webCreations } from "@/lib/library";
import { MyCreations } from "@wasifyai/ui";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

const FILTERS = ["songs", "images", "videos", "speeches", "transcripts", "lipsyncs"] as const;

/** My creations: the shared screen (also the desktop's Library), talking to the BFF, its cards real links. */
export function CreationsScreen({ show }: { show?: string }) {
  const router = useRouter();
  const nav = useMemo(() => webCreationsNav((href) => router.push(href)), [router]);
  const initialFilter = FILTERS.find((f) => f === show) ?? "all";
  return (
    <MyCreations
      api={webCreations}
      nav={nav}
      initialFilter={initialFilter}
      className="grid gap-5"
    />
  );
}
