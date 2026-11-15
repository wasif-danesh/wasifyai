"use client";
// Settings › Cloud keys (ADR-0095; ADR-0100 and its amendment of 2026-11-15; the mockup approved on 2026-11-15): keys
// only, never a model. Chat and writing keeps a key per text vendor. Media keeps one Runware, WaveSpeed and fal.ai key
// each, under Media, for every media product; each job goes to the cheapest offer with a key. A table shows which
// provider serves each media product and which products no key covers. The product's model picker lists, under Cloud,
// the models its keys can run. A key goes to the engine once and is never shown again.
import type {
  KeyProduct,
  KeyProvider,
  KeyTest,
  OwnKeys,
  OwnKeysApi,
  SavedKey,
} from "@wasifyai/client";
import { Check, Lock, Minus } from "lucide-react";
import { type ReactNode, useEffect, useId, useState } from "react";
import { Button } from "../components/button";
import { ConfirmDialog } from "../components/dialog";
import { Input } from "../components/input";
import { Label } from "../components/label";
import { Notice } from "../components/notice";
import { Select } from "../components/select";
import { useChoicesChanged } from "../models/context";

function problem(e: unknown): string {
  return e instanceof Error ? e.message : "That did not work.";
}

const titleOf = (providers: KeyProvider[], id: string) =>
  providers.find((v) => v.id === id)?.title ?? id;

/** Whose keys these are: the person's, on this computer; or the service's, kept by an admin on the web (CP11). */
export type KeysPlace = "computer" | "service";

/** The key row that serves every media product. */
const MEDIA = "media";

/** A card of the keys screen: a title, one line under it, then its rows. */
function Card({
  title,
  line,
  children,
}: {
  title: string;
  line?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="rounded-xl border bg-card">
      <div className="grid gap-0.5 px-4 pt-3.5 pb-2.5">
        <h3 className="m-0 font-medium text-base">{title}</h3>
        {line ? <p className="m-0 text-muted-foreground text-sm">{line}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function YourKeys({
  api,
  place = "computer",
}: {
  api: OwnKeysApi;
  place?: KeysPlace;
}) {
  const [keys, setKeys] = useState<OwnKeys | null>(null);
  const [error, setError] = useState<string | null>(null);
  // a key added or removed changes what each picker's Cloud tab lists: every screen hears it
  const changed = useChoicesChanged();

  useEffect(() => {
    api
      .list()
      .then(setKeys)
      .catch((e) => setError(problem(e)));
  }, [api]);

  if (!keys) {
    return error ? (
      <Notice tone="error" title="Your keys could not be read">
        {error}
      </Notice>
    ) : null;
  }
  const update = (next: OwnKeys) => {
    setKeys(next);
    changed();
  };
  const text = keys.products.filter((p) => p.kind === "text");
  const media = keys.products.find((p) => p.id === MEDIA);
  const served = keys.products.filter((p) => p.kind === "media" && p.id !== MEDIA);

  return (
    <div className="grid gap-4" aria-label={place === "service" ? "Service keys" : "Cloud keys"}>
      {place === "service" ? (
        <div className="grid gap-1.5">
          <h3 className="m-0 font-semibold text-base">Service keys</h3>
          <p className="m-0 text-muted-foreground text-sm">
            The service runs every picture, clip, voice, song, lip sync, 3D model and look on cloud
            models, on the keys below.
          </p>
          <p className="m-0 flex items-center gap-1.5 text-muted-foreground text-xs">
            <Lock aria-hidden="true" className="size-3.5" />A key is encrypted in the service's
            database and never shown again. Testing a key costs nothing.
          </p>
        </div>
      ) : (
        <div className="grid gap-1.5">
          <p className="m-0 text-muted-foreground text-sm">
            Add a provider's key to use its cloud models. They appear in each product's model
            picker, under Cloud.
          </p>
          <p className="m-0 flex items-center gap-1.5 text-muted-foreground text-xs">
            <Lock aria-hidden="true" className="size-3.5" />
            Keys stay in this computer's keychain and are never shown again. Testing a key costs
            nothing.
          </p>
        </div>
      )}
      {!keys.can_save ? (
        <Notice tone="warn" title="Keys cannot be kept here">
          {place === "service"
            ? "The service has no key to encrypt them with: set MEDIA_SECRETS_KEY and restart the API and the worker."
            : "This computer has nowhere safe to keep a key, so every product uses this computer's models."}
        </Notice>
      ) : null}
      {text.map((p) => (
        <Card key={p.id} title={p.title} line="A key from one text provider is enough.">
          <TextKeys
            api={api}
            product={p}
            providers={keys.providers}
            canSave={keys.can_save}
            onChanged={update}
          />
        </Card>
      ))}
      {media ? (
        <>
          <Card
            title="Media"
            line="To use every media product in the cloud, add a fal.ai key, or both a Runware and a WaveSpeed key. With more than one key, each job goes to the cheapest."
          >
            <ul className="m-0 list-none divide-y border-t p-0">
              {media.providers.map((id) => (
                <MediaKey
                  key={id}
                  api={api}
                  media={media}
                  provider={id}
                  providers={keys.providers}
                  canSave={keys.can_save}
                  onChanged={update}
                />
              ))}
            </ul>
          </Card>
          <Coverage media={media} served={served} providers={keys.providers} place={place} />
        </>
      ) : null}
    </div>
  );
}

/** The text vendors' keys of one product: each saved key, then "Add a key" with the vendors left. */
function TextKeys({
  api,
  product,
  providers,
  canSave,
  onChanged,
}: {
  api: OwnKeysApi;
  product: KeyProduct;
  providers: KeyProvider[];
  canSave: boolean;
  onChanged: (keys: OwnKeys) => void;
}) {
  const [adding, setAdding] = useState(false);
  const saved = new Set(product.keys.map((k) => k.provider));
  const left = product.providers.filter((id) => !saved.has(id));

  return (
    <ul className="m-0 list-none divide-y border-t p-0">
      {product.keys.map((k) => (
        <li key={k.provider} className="px-4 py-2.5">
          <KeyRow
            api={api}
            product={product}
            saved={k}
            title={titleOf(providers, k.provider)}
            inUse={product.use?.provider === k.provider ? product.use.title : null}
            onChanged={onChanged}
          />
        </li>
      ))}
      {product.keys.length === 0 && !adding ? (
        <li className="px-4 py-2.5 text-muted-foreground text-sm">
          No key: {product.title.toLowerCase()} uses this computer's models only.
        </li>
      ) : null}
      {adding ? (
        <li className="p-3">
          <AddKey
            api={api}
            product={product}
            providers={providers.filter((v) => left.includes(v.id))}
            onDone={(next) => {
              onChanged(next);
              setAdding(false);
            }}
            onCancel={() => setAdding(false)}
          />
        </li>
      ) : left.length && canSave ? (
        <li className="flex flex-wrap items-baseline gap-x-2 px-4 py-2.5 text-sm">
          <Button
            type="button"
            variant="link"
            className="h-auto p-0"
            aria-label={`Add a key for ${product.title}`}
            onClick={() => setAdding(true)}
          >
            + Add a key
          </Button>
          <span className="text-muted-foreground text-xs">
            {left.map((id) => titleOf(providers, id)).join(", ")}
          </span>
        </li>
      ) : null}
    </ul>
  );
}

/** One media provider's row: its saved key with Test and Remove, or "No key" with "Add a key". */
function MediaKey({
  api,
  media,
  provider,
  providers,
  canSave,
  onChanged,
}: {
  api: OwnKeysApi;
  media: KeyProduct;
  provider: string;
  providers: KeyProvider[];
  canSave: boolean;
  onChanged: (keys: OwnKeys) => void;
}) {
  const [adding, setAdding] = useState(false);
  const title = titleOf(providers, provider);
  const saved = media.keys.find((k) => k.provider === provider);
  if (saved) {
    return (
      <li className="px-4 py-2.5">
        <KeyRow
          api={api}
          product={media}
          saved={saved}
          title={title}
          inUse={null}
          onChanged={onChanged}
        />
      </li>
    );
  }
  return (
    <li className="grid gap-2 px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium text-sm">{title}</span>
        <span className="text-muted-foreground text-sm">No key</span>
        {canSave && !adding ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="ms-auto"
            aria-label={`Add a ${title} key`}
            onClick={() => setAdding(true)}
          >
            Add a key
          </Button>
        ) : null}
      </div>
      {adding ? (
        <AddKey
          api={api}
          product={media}
          providers={providers.filter((v) => v.id === provider)}
          onDone={(next) => {
            onChanged(next);
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      ) : null}
    </li>
  );
}

/** Media products that the same providers serve share a row of the table. */
type Group = { titles: string[]; providers: string[] };

function groupsOf(served: KeyProduct[]): Group[] {
  const groups: Group[] = [];
  for (const p of served) {
    const same = groups.find((g) => g.providers.join() === p.providers.join());
    if (same) same.titles.push(p.title);
    else groups.push({ titles: [p.title], providers: [...p.providers] });
  }
  return groups;
}

/** What the Media keys cover: products by provider, with the ones no key covers named. */
function Coverage({
  media,
  served,
  providers,
  place,
}: {
  media: KeyProduct;
  served: KeyProduct[];
  providers: KeyProvider[];
  place: KeysPlace;
}) {
  const have = new Set(media.keys.map((k) => k.provider));
  const covered = served.filter((p) => p.providers.some((id) => have.has(id))).length;
  const elsewhere =
    place === "service" ? "cannot run until a key covers them" : "run on this computer's models";
  const status =
    covered === served.length
      ? { tone: "text-ok", words: "Your keys cover every media product." }
      : covered === 0
        ? {
            tone: "text-muted-foreground",
            words: `No media key yet: every media product ${place === "service" ? "is off" : "runs on this computer's models"}.`,
          }
        : {
            tone: "text-warn",
            words: `Your keys cover ${covered} of ${served.length} media products. The rest ${elsewhere}.`,
          };
  return (
    <Card
      title="What your keys cover"
      line={
        place === "service"
          ? undefined
          : "A product a key covers runs on this computer until you choose a cloud model in its picker."
      }
    >
      <output className={`m-0 block px-4 pb-2.5 text-sm ${status.tone}`}>{status.words}</output>
      <table className="w-full table-fixed border-collapse text-sm">
        <caption className="sr-only">Which provider serves each media product</caption>
        <thead>
          <tr className="border-t">
            <th
              scope="col"
              className="w-1/2 px-4 py-2 text-start font-medium text-muted-foreground text-xs"
            >
              Product
            </th>
            {media.providers.map((id) => (
              <th
                key={id}
                scope="col"
                className="px-2 py-2 text-center font-medium text-muted-foreground text-xs"
              >
                {titleOf(providers, id)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groupsOf(served).map((g) => {
            const none = !g.providers.some((id) => have.has(id));
            return (
              <tr key={g.titles.join()} className="border-t align-top">
                <th scope="row" className="px-4 py-2.5 text-start font-normal">
                  {g.titles.join(", ")}
                  {none ? (
                    <span className="block text-warn text-xs">
                      Needs a {g.providers.map((id) => titleOf(providers, id)).join(" or ")} key
                    </span>
                  ) : null}
                </th>
                {media.providers.map((id) => (
                  <td key={id} className="px-2 py-2.5 text-center">
                    {!g.providers.includes(id) ? (
                      <Minus
                        role="img"
                        aria-label="Not offered"
                        className="inline size-4 text-muted-foreground/60"
                      />
                    ) : have.has(id) ? (
                      <Check
                        role="img"
                        aria-label="Covered by your key"
                        className="inline size-4 text-ok"
                      />
                    ) : (
                      <Check
                        role="img"
                        aria-label="Offered, no key saved"
                        className="inline size-4 text-muted-foreground/60"
                      />
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}

function KeyRow({
  api,
  product,
  saved,
  title,
  inUse,
  onChanged,
}: {
  api: OwnKeysApi;
  product: KeyProduct;
  saved: SavedKey;
  title: string;
  inUse: string | null;
  onChanged: (keys: OwnKeys) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<OwnKeys>) {
    setBusy(true);
    setError(null);
    try {
      onChanged(await fn());
    } catch (e) {
      setError(problem(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium text-sm">{title}</span>
        <span
          className={`inline-flex items-center gap-1.5 text-sm ${saved.state === "ok" ? "text-ok" : "text-destructive"}`}
        >
          <span
            aria-hidden="true"
            className={`size-2 rounded-full ${saved.state === "ok" ? "bg-ok" : "bg-destructive"}`}
          />
          {saved.state === "ok" ? "Works" : "Key not working"}
        </span>
        <span className="ms-auto flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            aria-label={`Test the ${title} key for ${product.title}`}
            onClick={() => void run(() => api.check(product.id, saved.provider))}
          >
            {busy ? "Testing…" : "Test"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            aria-label={`Remove the ${title} key for ${product.title}`}
            onClick={() => setRemoving(true)}
          >
            Remove
          </Button>
        </span>
      </div>
      {saved.state === "bad" && saved.said ? (
        <span className="text-muted-foreground text-xs">{saved.said}</span>
      ) : null}
      {inUse ? <span className="text-muted-foreground text-xs">In use: {inUse}</span> : null}
      {error ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {error}
        </p>
      ) : null}
      {removing ? (
        <ConfirmDialog
          title={`Remove the ${title} key for ${product.title}?`}
          message={
            product.id === MEDIA
              ? `The key is deleted and ${title}'s models leave the picker of every media product. A product whose model only ${title} runs goes back to this computer's model.`
              : `The key is deleted from this computer's keychain and ${title}'s models leave the ${product.title} picker.${inUse ? ` ${product.title} goes back to this computer's model.` : ""}`
          }
          confirmLabel="Remove"
          onConfirm={() => {
            setRemoving(false);
            void run(() => api.remove(product.id, saved.provider));
          }}
          onCancel={() => setRemoving(false)}
        />
      ) : null}
    </div>
  );
}

function AddKey({
  api,
  product,
  providers,
  onDone,
  onCancel,
}: {
  api: OwnKeysApi;
  product: KeyProduct;
  providers: KeyProvider[];
  onDone: (keys: OwnKeys) => void;
  onCancel: () => void;
}) {
  const [provider, setProvider] = useState(providers[0]?.id ?? "");
  const chosen = providers.find((v) => v.id === provider);
  const [key, setKey] = useState("");
  const [tried, setTried] = useState<KeyTest | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ids = { provider: useId(), key: useId() };
  const body = { key: key.trim() };
  const ready = Boolean(provider && key.trim());

  async function run(what: "test" | "save", fn: () => Promise<void>) {
    setBusy(what);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(problem(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      className="grid gap-3 rounded-lg border bg-muted/40 p-3"
      aria-label={`Add a key for ${product.title}`}
    >
      {providers.length === 1 ? (
        <p className="m-0 font-medium text-sm">Your {providers[0]?.title} key</p>
      ) : null}
      <div
        className={
          providers.length > 1
            ? "grid gap-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]"
            : "grid gap-3"
        }
      >
        <div className={providers.length > 1 ? "grid gap-1.5" : "hidden"}>
          <Label htmlFor={ids.provider}>Provider</Label>
          <Select
            id={ids.provider}
            value={provider || undefined}
            onValueChange={(v) => {
              setProvider(v);
              setTried(null);
            }}
            options={providers.map((v) => ({ value: v.id, label: v.title }))}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={ids.key}>Key</Label>
          <Input
            id={ids.key}
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            placeholder="Paste the key"
            onChange={(e) => {
              setKey(e.target.value);
              setTried(null);
            }}
          />
        </div>
      </div>
      <p className="m-0 text-muted-foreground text-xs">
        What you make with a {chosen?.title ?? "cloud"} model is sent to{" "}
        {chosen?.host || "that server"} with this key. Their terms and prices apply.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={!ready || busy !== null}
          onClick={() =>
            void run("test", async () => setTried(await api.test(product.id, provider, body)))
          }
        >
          {busy === "test" ? "Testing…" : "Test"}
        </Button>
        <Button
          type="button"
          disabled={!ready || busy !== null}
          onClick={() =>
            void run("save", async () => onDone(await api.save(product.id, provider, body)))
          }
        >
          {busy === "save" ? "Saving…" : "Save"}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        {tried ? (
          <output className={tried.ok ? "text-ok text-sm" : "text-destructive text-sm"}>
            {tried.ok
              ? `It answered in ${tried.ms} ms. Nothing is saved yet.`
              : (tried.said ?? "It did not work.")}
          </output>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {error}
        </p>
      ) : null}
    </section>
  );
}
