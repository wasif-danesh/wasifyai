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

/**
 * A style's title as a person reads it. A style found in another tool or added from a file keeps its file name
 * ("ena_flux2_klein_4b_full", "wasify-ena-b37ba287"), which the screen review of 2026-11-20 found unreadable:
 * the pieces become words and a trailing hash is dropped. A title with a space is a person's and is left as it is.
 */
export function styleTitle(title: string): string {
  const raw = title.trim().replace(/\.safetensors$/i, "");
  if (!raw || /\s/.test(raw)) return raw;
  const words = raw
    .replace(/[-_][0-9a-f]{6,}$/i, "")
    .split(/[-_]+/)
    .filter(Boolean)
    .map((w) => (/^\d+[bm]$/i.test(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)));
  return words.join(" ") || raw;
}
