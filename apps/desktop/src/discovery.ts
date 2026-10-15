// SPDX-License-Identifier: AGPL-3.0-only
// The engine's discovery routes (`/desktop/discovery`, services/api/src/wasifyai_api/desktop_discovery.py,
// ADR-0063): the models other tools left on this computer, and what the app can do with each.
import type { Transport } from "@wasifyai/client";
import { HttpError } from "@wasifyai/client";

export type FoundKind =
  | "language"
  | "embedding"
  | "diffusion"
  | "video"
  | "lora"
  | "vae"
  | "text_encoder"
  | "controlnet"
  | "upscaler"
  | "vision_encoder"
  | "other"
  | "unknown";

/** ready: used already · can_use: one click · later: a planned stage · unsupported: cannot be used */
export type FoundState = "ready" | "can_use" | "later" | "unsupported";

export type FoundModel = {
  id: string;
  name: string;
  kind: FoundKind;
  family: string;
  format: string;
  quant: string;
  size: number;
  path: string;
  tool: string;
  tool_title: string;
  licence: string;
  state: FoundState;
  reason: string;
  use_root: string | null;
  needs_gb: number;
};

export type DiscoveryState = {
  enabled: boolean;
  running: boolean;
  /** seconds since the epoch, null before the first scan */
  scanned_at: number | null;
  truncated: boolean;
  items: FoundModel[];
  scanned: { tool: string; folder: string; found: number }[];
  servers: { tool: string; title: string; url: string; kind: string }[];
  folders: string[];
  suggested: { tool: string; folder: string }[];
};

/** The order the groups are shown in, and the words for them. */
export const KIND_GROUPS: { kind: FoundKind[]; title: string }[] = [
  { kind: ["language"], title: "Language models" },
  { kind: ["diffusion"], title: "Image models" },
  { kind: ["video"], title: "Video models" },
  { kind: ["lora"], title: "LoRAs" },
  { kind: ["embedding"], title: "Embedding models" },
  {
    kind: ["vae", "text_encoder", "controlnet", "upscaler", "vision_encoder"],
    title: "Parts of image models",
  },
  { kind: ["other", "unknown"], title: "Other" },
];

export type Group = { title: string; items: FoundModel[] };

export function groupFound(items: FoundModel[]): Group[] {
  return KIND_GROUPS.map((g) => ({
    title: g.title,
    items: items.filter((i) => g.kind.includes(i.kind)),
  })).filter((g) => g.items.length > 0);
}

export const STATE_LABEL: Record<FoundState, string> = {
  ready: "In use",
  can_use: "Can be used",
  later: "Not used yet",
  unsupported: "Not supported",
};

/** "Q4_K_M · llama" and the like: what a person who knows models would want to see. */
export function detailOf(m: FoundModel): string {
  return [m.family, m.quant, m.format === "repo" ? "" : m.format.toUpperCase()]
    .filter(Boolean)
    .join(" · ");
}

async function json<T>(transport: Transport, path: string, init?: RequestInit): Promise<T> {
  const res = await transport.fetch(path, init);
  if (!res.ok) {
    let detail = `The engine answered ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // not JSON
    }
    throw new HttpError(res.status, detail);
  }
  return (await res.json()) as T;
}

export function createDiscoveryApi(transport: Transport) {
  return {
    state: () => json<DiscoveryState>(transport, "/desktop/discovery"),
    scan: () =>
      json<{ running: boolean }>(transport, "/desktop/discovery/scan", { method: "POST" }),
    settings: (enabled: boolean, folders: string[]) =>
      json<DiscoveryState>(transport, "/desktop/discovery/settings", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled, folders }),
      }),
    use: (id: string) =>
      json<{ folder: string }>(transport, "/desktop/discovery/use", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id }),
      }),
  };
}

export type DiscoveryApi = ReturnType<typeof createDiscoveryApi>;
