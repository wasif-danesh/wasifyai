"use client";
// Settings > Your keys (ADR-0095, amendment of 2026-11-11; the approved mockup is docs/spikes/provider-keys-mockup.html,
// third version): keys only. One row per product with the provider keys saved for it (several are fine), each with
// Test and Remove, and "Add a key". A row never names a model: the product's model picker lists the models of each
// provider with a key under Cloud. A key goes to the engine once and is never shown again.
import type {
  KeyProduct,
  KeyProvider,
  KeyTest,
  OwnKeys,
  OwnKeysApi,
  SavedKey,
} from "@wasifyai/client";
import { useEffect, useId, useState } from "react";
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

export function YourKeys({ api }: { api: OwnKeysApi }) {
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

  return (
    <section className="grid gap-4" aria-label="Your keys">
      <h3 className="m-0 font-semibold text-base">Your keys</h3>
      <p className="m-0 text-muted-foreground text-sm">
        Save a provider key for a product, and that provider's models for it appear in the product's
        model picker, under Cloud. A key is kept in this computer's keychain, used only by its
        product, and never shown again. Testing a key costs nothing.
      </p>
      {!keys.can_save ? (
        <Notice tone="warn" title="Keys cannot be kept here">
          This computer has nowhere safe to keep a key, so every product uses this computer's
          models.
        </Notice>
      ) : null}
      <ul className="m-0 grid list-none gap-0 divide-y rounded-xl border p-0">
        {keys.products.map((p) => (
          <ProductKeys
            key={p.id}
            api={api}
            product={p}
            providers={keys.providers}
            canSave={keys.can_save}
            onChanged={update}
          />
        ))}
      </ul>
    </section>
  );
}

function ProductKeys({
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
    <li className="grid gap-2 p-4 sm:grid-cols-[10rem_minmax(0,1fr)]" aria-label={product.title}>
      <div className="font-medium text-sm">{product.title}</div>
      <div className="grid min-w-0 gap-2">
        {product.keys.map((k) => (
          <KeyRow
            key={k.provider}
            api={api}
            product={product}
            saved={k}
            title={titleOf(providers, k.provider)}
            inUse={product.use?.provider === k.provider ? product.use.title : null}
            onChanged={onChanged}
          />
        ))}
        {product.keys.length === 0 && !adding ? (
          <p className="m-0 text-muted-foreground text-sm">
            No key: {product.title} uses this computer's models only.
          </p>
        ) : null}
        {adding ? (
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
        ) : left.length && canSave ? (
          <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
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
          </div>
        ) : null}
      </div>
    </li>
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
          {saved.state === "ok" ? "Saved · works" : "Key not working"}
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
          message={`The key is deleted from this computer's keychain and ${title}'s models leave the ${product.title} picker.${inUse ? ` ${product.title} goes back to this computer's model.` : ""}`}
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
      <div className="grid gap-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]">
        <div className="grid gap-1.5">
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
