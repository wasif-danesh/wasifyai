// SPDX-License-Identifier: AGPL-3.0-only
// The engine's model hub routes (`/desktop/hub`, services/api/src/wasifyai_api/desktop_hub.py,
// ADR-0064): browse open-weight models on Hugging Face and fetch one. The window never talks to the
// internet itself; everything goes through the engine.
import type { Transport } from "@wasifyai/client";
import { HttpError } from "@wasifyai/client";
import type { Fit } from "./models";

export type Capability = "language" | "embedding" | "image" | "video";
export type Sort = "downloads" | "likes" | "recent";

export type ShelfItem = {
  repo: string;
  title: string;
  capability: string;
  note: string;
  /** the one we measured and suggest to start with */
  recommended: boolean;
};

export type HubState = {
  enabled: boolean;
  has_token: boolean;
  /** a token is kept in the app's secret store (the keychain); never the token itself */
  token_set?: boolean;
  can_save_token?: boolean;
  shelf: ShelfItem[];
  capabilities: Capability[];
};

export type HubResult = {
  id: string;
  publisher: string;
  name: string;
  downloads: number;
  likes: number;
  updated: string | null;
  capability: string;
  pipeline: string | null;
  gated: boolean;
  gguf: boolean;
  runnable: boolean;
};

export type Variant = {
  id: string;
  name: string;
  quant: string;
  files: string[];
  size: number;
  sizes: number[];
  fit: Fit | null;
};

export type HubModel = {
  id: string;
  commit: string | null;
  stale: boolean;
  capability: string;
  pipeline: string | null;
  gated: boolean;
  downloads: number;
  likes: number;
  updated: string | null;
  tags: string[];
  architecture: string | null;
  context_length: number | null;
  parameters: number | null;
  has_chat_template: boolean;
  variants: Variant[];
  runnable: boolean;
};

export const CAPABILITY_LABEL: Record<Capability, string> = {
  language: "Language models",
  embedding: "Embedding models",
  image: "Image models",
  video: "Video models",
};

/** "1.2M", "34K", "980": a count for a person. */
export function compactCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}

/** "3.8B", "600M": parameters for a person. */
export function paramsLabel(n: number | null): string {
  if (!n) return "";
  if (n >= 1e9) return `${(n / 1e9).toFixed(n >= 1e10 ? 0 : 1)}B`;
  return `${Math.round(n / 1e6)}M`;
}

/** "3 days ago", "2 months ago", "just now". */
export function ago(iso: string | null, now = new Date()): string {
  if (!iso) return "";
  const days = Math.floor((now.getTime() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days < 2) return "yesterday";
  if (days < 60) return `${days} days ago`;
  if (days < 730) return `${Math.round(days / 30)} months ago`;
  return `${Math.round(days / 365)} years ago`;
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

export function createHubApi(transport: Transport) {
  const headers = { "content-type": "application/json" };
  return {
    state: () => json<HubState>(transport, "/desktop/hub/state"),
    setEnabled: (enabled: boolean) =>
      json<{ enabled: boolean }>(transport, "/desktop/hub/consent", {
        method: "PUT",
        headers,
        body: JSON.stringify({ enabled }),
      }),
    setToken: (token: string) =>
      json<{ token_set: boolean }>(transport, "/desktop/hub/token", {
        method: "PUT",
        headers,
        body: JSON.stringify({ token }),
      }),
    removeToken: () =>
      json<{ token_set: boolean }>(transport, "/desktop/hub/token", { method: "DELETE" }),
    search: (q: string, capability: Capability, sort: Sort) =>
      json<{ items: HubResult[]; stale: boolean }>(
        transport,
        `/desktop/hub/search?${new URLSearchParams({ q, capability, sort })}`,
      ),
    model: (repo: string) => json<HubModel>(transport, `/desktop/hub/models/${repo}`),
    readme: (repo: string) =>
      json<{ text: string }>(transport, `/desktop/hub/models/${repo}/readme`),
    download: (repo: string, variant: Variant, acceptMemory = false) =>
      json<{ id: string; status: string; bytes_total: number }>(
        transport,
        "/desktop/hub/download",
        {
          method: "POST",
          headers,
          body: JSON.stringify({
            repo,
            files: variant.files,
            bytes: variant.size,
            ...(acceptMemory ? { accept_memory: true } : {}),
          }),
        },
      ),
    remove: (itemId: string) =>
      json<{ removed: boolean }>(transport, `/desktop/hub/files/${encodeURIComponent(itemId)}`, {
        method: "DELETE",
      }),
  };
}

export type HubApi = ReturnType<typeof createHubApi>;
