// Settings > Your keys (ADR-0095): each product runs on this computer or with the person's own provider
// key. The engine's `/desktop/keys` routes; a key goes in once and is never answered back.
import type { Transport } from "./transport";
import { HttpError } from "./transport";

export type KeyKind = "text" | "media";
export type KeyMode = "here" | "key";

export type KeyProduct = {
  id: string;
  title: string;
  kind: KeyKind;
  mode: KeyMode;
  provider: string | null;
  model: string | null;
  base_url: string | null;
  /** a key is kept for this product (in the keychain); never the key itself */
  key_saved: boolean;
  /** "here": runs on this computer; "ok": the key worked when last tested; "bad": it did not */
  state: "here" | "ok" | "bad";
  /** why the key did not work, in words */
  said: string | null;
  tested_at: number | null;
  /** model names to suggest for a media product */
  models: string[];
};

export type KeyProvider = {
  id: string;
  title: string;
  kind: KeyKind;
  /** where what is made goes: "fal.ai" */
  host: string;
  /** an OpenAI-compatible server: the person gives its address */
  needs_base: boolean;
  /** model names to suggest for a text provider */
  models: string[];
};

export type OwnKeys = { products: KeyProduct[]; providers: KeyProvider[]; can_save: boolean };

export type KeyChoice = {
  provider?: string;
  model?: string;
  base_url?: string;
  /** write-only: left out to use the key already saved */
  key?: string;
};

export type KeyTest = { ok: boolean; ms: number; said: string | null };

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

export function createOwnKeysApi(transport: Transport) {
  return {
    list: () => json<OwnKeys>(transport, BASE),
    /** One small request with the key given (or the one saved). Nothing is saved. */
    test: (product: string, choice: KeyChoice) =>
      json<KeyTest>(transport, `${BASE}/${product}/test`, send("POST", choice)),
    /** "key": tested first and saved only when it works; "here": back to this computer, the key kept. */
    save: (product: string, mode: KeyMode, choice: KeyChoice = {}) =>
      json<OwnKeys>(transport, `${BASE}/${product}`, send("PUT", { mode, ...choice })),
    /** Test what is saved and keep the answer. */
    check: (product: string) => json<OwnKeys>(transport, `${BASE}/${product}/check`, send("POST")),
    /** "Use the same key as …": copied inside the keychain, never through the window. */
    copy: (product: string, source: string) =>
      json<OwnKeys>(transport, `${BASE}/${product}/copy`, send("POST", { source })),
    remove: (product: string) => json<OwnKeys>(transport, `${BASE}/${product}`, send("DELETE")),
  };
}

export type OwnKeysApi = ReturnType<typeof createOwnKeysApi>;
