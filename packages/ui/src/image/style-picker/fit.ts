import type { Style } from "@wasifyai/client";
import { formatBytes } from "../../notebook/format";

/** What the file says it was made for, in words (ADR-0091 decision 6, S0). */
export function fitLine(
  s: Pick<Style, "fit" | "model" | "made_for_base" | "size" | "unused_parts">,
): string {
  const size = formatBytes(s.size);
  if (s.fit === "other") return `Made for ${s.model ?? "another model"}: it would give noise here`;
  if (s.fit === "unsure") return `Not sure which model this was made for · ${size}`;
  const parts = [`Made for ${s.model} · ${size}`];
  if (s.made_for_base) parts.push("made for klein base: the look may not show on this model");
  if (s.unused_parts > 0) parts.push("a few parts of it are not used here");
  return parts.join(" · ");
}
