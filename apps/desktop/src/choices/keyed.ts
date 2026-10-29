// SPDX-License-Identifier: AGPL-3.0-only
// A product on the person's own key (ADR-0095): its row in the model picker, the one in use while the product runs
// there. Choosing a model on this computer takes the product off the key; the key stays saved.
import type { OwnKeys, OwnKeysApi } from "@wasifyai/client";
import type { ModelChoice } from "@wasifyai/ui";

/** The picker id of a product's keyed row: `key:chat`, `key:images`, `key:video`. */
export const keyedId = (product: string) => `key:${product}`;
export const isKeyed = (id: string | null | undefined) => Boolean(id?.startsWith("key:"));

/** The row that says `product` runs with the person's key, or null while it runs on this computer. */
export function keyedRow(keys: OwnKeys | null, product: string): ModelChoice | null {
  const p = keys?.products.find((x) => x.id === product);
  if (!keys || !p || p.mode !== "key") return null;
  const provider = keys.providers.find((v) => v.id === p.provider);
  const name = provider?.title ?? p.provider ?? "your provider";
  const what = product === "chat" ? "what you write" : "what you describe and the pictures you add";
  return {
    id: keyedId(product),
    title: `${p.model ?? "Your model"} · with your key · ${name}`,
    plain: `Runs with your key, through ${name}: ${what} is sent there. Change it in Settings › Your keys.`,
    tier: "recommended",
    state: "ready",
    chosen: true,
    downloadBytes: 0,
    engineBytes: 0,
    engineName: null,
    fit: null,
    fitReason: null,
    source: "server",
    from: provider?.host || null,
  };
}

/** The rows with the keyed one first and in use, when there is one. */
export function withKeyed(rows: ModelChoice[], keyed: ModelChoice | null): ModelChoice[] {
  return keyed ? [keyed, ...rows.map((c) => ({ ...c, chosen: false }))] : rows;
}

/** Before a model on this computer is chosen: take the product off the key. True when `id` is the keyed row. */
export async function leaveKey(keys: OwnKeysApi | undefined, product: string, id: string) {
  if (id === keyedId(product)) return true;
  const list = await keys?.list().catch(() => null);
  if (keyedRow(list ?? null, product)) await keys?.save(product, "here");
  return false;
}
