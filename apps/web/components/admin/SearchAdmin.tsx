"use client";

import { webAssistant } from "@/lib/library";
import { SearchSettings } from "@wasifyai/ui";

/** Admin > Search: the search service the assistant uses for everyone, and its key (ADR-0083, on a service). */
export function SearchAdmin() {
  return <SearchSettings assistant={webAssistant} place="service" />;
}
