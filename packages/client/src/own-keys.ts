// Settings > Your keys (ADR-0095, amendment of 2026-11-11): each product keeps provider keys, never a model. A
// product's model picker lists, under Cloud, the models of every provider with a key, and choosing one makes the
// product run there. The engine's `/desktop/keys` routes; a key goes in once and is never answered back.
import type { Transport } from "./transport";
import { HttpError } from "./transport";

export type KeyKind = "text" | "media";

/** A key saved for a product: its state, never the key itself. */
export type SavedKey = {
  provider: string;
  /** "ok": the key worked when last tested; "bad": it did not */
  state: "ok" | "bad";
  /** why the key did not work, in words */
  said: string | null;
  tested_at: number | null;
  /** another OpenAI-compatible server only: its address and the model it runs */
  base_url: string | null;
  model: string | null;
};

/** The cloud model a product runs on now (null: this computer). */
export type KeyUse = { provider: string; model: string; title: string; price: string };

export type KeyProduct = {
  id: string;
  title: string;
  kind: KeyKind;
  /** the providers a key can be saved for under this product */
  providers: string[];
  keys: SavedKey[];
  use: KeyUse | null;
};

export type KeyProvider = {
  id: string;
  title: string;
  /** where what is made goes: "fal.ai" */
  host: string;
  /** an OpenAI-compatible server: the person gives its address and model */
  needs_base: boolean;
};

export type OwnKeys = { products: KeyProduct[]; providers: KeyProvider[]; can_save: boolean };

/** What goes with a key; `base_url` and `model` only for another OpenAI-compatible server. */
export type KeyBody = {
  /** write-only: left out to use the key already saved */
  key?: string;
  base_url?: string;
  model?: string;
};

export type KeyTest = { ok: boolean; ms: number; said: string | null };

/** One row of a picker's Cloud tab. */
export type CloudModel = {
  provider: string;
  provider_title: string;
  host: string;
  model: string;
  title: string;
  about: string;
  /** as the provider lists it, in words: "$0.20 per second" */
  price: string;
  /** the key worked when last tested */
  works: boolean;
  chosen: boolean;
};

export type CloudModels = { product: string; models: CloudModel[]; has_keys: boolean };

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

const BASE = "/desktop/keys";
const headers = { "content-type": "application/json" };
const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers,
  body: body === undefined ? undefined : JSON.stringify(body),
});
const keyPath = (product: string, provider: string) =>
  `${BASE}/${encodeURIComponent(product)}/keys/${encodeURIComponent(provider)}`;

export function createOwnKeysApi(transport: Transport) {
  return {
    list: () => json<OwnKeys>(transport, BASE),
    /** One small request with the key given (or the one saved). Nothing is saved. */
    test: (product: string, provider: string, body: KeyBody = {}) =>
      json<KeyTest>(transport, `${keyPath(product, provider)}/test`, send("POST", body)),
    /** Tested first and saved only when it works. */
    save: (product: string, provider: string, body: KeyBody) =>
      json<OwnKeys>(transport, keyPath(product, provider), send("PUT", body)),
    /** Test what is saved and keep the answer. */
    check: (product: string, provider: string) =>
      json<OwnKeys>(transport, `${keyPath(product, provider)}/check`, send("POST")),
    /** Forget the key; a product running on that provider goes back to this computer. */
    remove: (product: string, provider: string) =>
      json<OwnKeys>(transport, keyPath(product, provider), send("DELETE")),
    /** The picker's Cloud tab: the models of every provider with a key for `product`. */
    cloud: (product: string) =>
      json<CloudModels>(transport, `${BASE}/${encodeURIComponent(product)}/cloud`),
    /** Run `product` on a cloud model, or on this computer again (`null`). The keys stay. */
    use: (product: string, choice: { provider: string; model: string } | null) =>
      json<CloudModels>(
        transport,
        `${BASE}/${encodeURIComponent(product)}/use`,
        send("PUT", choice ?? { provider: null }),
      ),
  };
}

export type OwnKeysApi = ReturnType<typeof createOwnKeysApi>;
