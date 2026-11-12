// SPDX-License-Identifier: AGPL-3.0-only
// Cloud models in the picker (ADR-0095, amendment of 2026-11-11): every model of every provider with a key saved for
// the product in Settings › Your keys is a row under the picker's Cloud tab. Choosing one makes the product run there;
// choosing a model on this computer takes the product off the cloud. The keys stay saved either way.
import type { CloudModel, OwnKeysApi } from "@wasifyai/client";
import type { ModelChoice } from "@wasifyai/ui";
import { routePath } from "../router";

/** A cloud row's picker id: `cloud:<product>:<provider>:<model>` (a model may hold colons: `runware:100@1`). */
export const cloudId = (product: string, provider: string, model: string) =>
  `cloud:${product}:${provider}:${model}`;
export const isCloud = (id: string | null | undefined) => Boolean(id?.startsWith("cloud:"));

/** The id the voice engine lists a product's cloud model under while it is in use (`key:lipsync`). */
export const engineKeyedId = (product: string) => `key:${product}`;
export const isEngineKeyed = (id: string | null | undefined) => Boolean(id?.startsWith("key:"));

export function parseCloud(
  id: string,
): { product: string; provider: string; model: string } | null {
  if (!isCloud(id)) return null;
  const [, product, provider, ...rest] = id.split(":");
  const model = rest.join(":");
  return product && provider && model ? { product, provider, model } : null;
}

/** The product names, for the picker's Cloud tab when no key is saved. */
const PRODUCT_TITLES: Record<string, string> = {
  chat: "Chat and writing",
  images: "Images",
  video: "Video",
  voice: "Voice",
  music: "Music",
  sfx: "Sound effects",
  lipsync: "Lip sync",
  model3d: "3D",
};

/** What leaves the computer while a product runs on a cloud model. */
const SENT: Record<string, string> = {
  chat: "what you write",
  voice: "the words it speaks",
  music: "what you describe and your lyrics",
  sfx: "what you describe",
  lipsync: "the picture and the voice",
  model3d: "the picture you add",
};

/** Settings › Your keys, from the picker's Cloud tab. */
export function openYourKeys() {
  window.location.hash = routePath("settings");
  window.setTimeout(
    () => document.getElementById("settings-keys")?.scrollIntoView({ block: "start" }),
    150,
  );
}

/** The `cloud` a group's ChoicesApi carries: the product's name and the way to its keys. */
export function cloudOf(products: string[]) {
  const titles = products.map((p) => PRODUCT_TITLES[p] ?? p);
  return { product: titles.join(" or "), setUp: openYourKeys };
}

export function cloudRow(product: string, m: CloudModel, engineId?: string): ModelChoice {
  const what = SENT[product] ?? "what you describe and the pictures you add";
  return {
    id: cloudId(product, m.provider, m.model),
    title: m.title,
    plain:
      `${m.about} Runs on ${m.provider_title} with your key, which sends ${what} there.`.trim(),
    tier: "also",
    state: "ready",
    chosen: m.chosen,
    downloadBytes: 0,
    engineBytes: 0,
    engineName: null,
    fit: null,
    fitReason: null,
    source: "server",
    from: m.host || null,
    place: "cloud",
    provider: m.provider,
    providerTitle: m.provider_title,
    price: m.price,
    ...(m.speed ? { speed: m.speed } : {}),
    works: m.works,
    ...(engineId ? { engineId } : {}),
  };
}

/** The Cloud tab's rows of `product` (none when the keys cannot be read). */
export async function cloudRows(
  keys: OwnKeysApi | undefined,
  product: string,
  engineId?: string,
): Promise<ModelChoice[]> {
  const list = await keys?.cloud(product).catch(() => null);
  return (list?.models ?? []).map((m) => cloudRow(product, m, engineId));
}

/** This computer's rows and the cloud ones; while a cloud model is in use, no row of this computer is. */
export function withCloud(local: ModelChoice[], cloud: ModelChoice[]): ModelChoice[] {
  const onCloud = cloud.some((c) => c.chosen);
  return [...(onCloud ? local.map((c) => ({ ...c, chosen: false })) : local), ...cloud];
}

/**
 * Choosing a row: a cloud one makes its product run there (true: nothing else to do); one on this computer takes
 * `product` off the cloud first (false: the caller goes on choosing it).
 */
export async function chooseCloud(keys: OwnKeysApi | undefined, product: string, id: string) {
  const cloud = parseCloud(id);
  if (cloud) {
    await keys?.use(cloud.product, { provider: cloud.provider, model: cloud.model });
    return true;
  }
  const list = await keys?.list().catch(() => null);
  if (list?.products.find((p) => p.id === product)?.use) await keys?.use(product, null);
  return false;
}
