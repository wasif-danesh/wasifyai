"use client";
// Settings > Your keys (ADR-0095, stage K1; the approved mockup is docs/spikes/own-keys-mockup.html): every product
// with where it runs, and one product open to change: On this computer or With my key, the provider, the model, the
// key, Test, Save and Remove. A key goes to the engine once and is never shown again.
import type { KeyProduct, KeyProvider, KeyTest, OwnKeys, OwnKeysApi } from "@wasifyai/client";
import { useEffect, useId, useState } from "react";
import { Button } from "../components/button";
import { ConfirmDialog } from "../components/dialog";
import { Input } from "../components/input";
import { Label } from "../components/label";
import { Notice } from "../components/notice";
import { Segmented } from "../components/segmented";
import { Select } from "../components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/table";
import { useChoicesChanged } from "../models/context";

const STATE: Record<KeyProduct["state"], { dot: string; text: string }> = {
  here: { dot: "bg-muted-foreground", text: "On this computer" },
  ok: { dot: "bg-ok", text: "With my key" },
  bad: { dot: "bg-destructive", text: "Key not working" },
};

function problem(e: unknown): string {
  return e instanceof Error ? e.message : "That did not work.";
}

function where(p: KeyProduct, providers: KeyProvider[]): string {
  if (p.mode === "here") return "This computer";
  const v = providers.find((x) => x.id === p.provider);
  return [v?.title ?? p.provider, p.model].filter(Boolean).join(" · ");
}

export function YourKeys({ api }: { api: OwnKeysApi }) {
  const [keys, setKeys] = useState<OwnKeys | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // where a product runs changes what the model button says: every screen hears it
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
  const editing = keys.products.find((p) => p.id === open) ?? null;

  return (
    <section className="grid gap-4" aria-label="Your keys">
      <h3 className="m-0 font-semibold text-base">Your keys</h3>
      <p className="m-0 text-muted-foreground text-sm">
        Each product can run on this computer or with your own provider key. A key is kept in this
        computer's keychain, used only by its product, and never shown again.
      </p>
      {!keys.can_save ? (
        <Notice tone="warn" title="Keys cannot be kept here">
          This computer has nowhere safe to keep a key, so every product runs on this computer.
        </Notice>
      ) : null}
      <Table aria-label="Products and their keys">
        <TableHeader>
          <TableRow>
            <TableHead scope="col">Product</TableHead>
            <TableHead scope="col">Runs</TableHead>
            <TableHead scope="col">Provider and model</TableHead>
            <TableHead scope="col">
              <span className="sr-only">Change</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.products.map((p) => (
            <TableRow key={p.id}>
              <TableHead scope="row" className="font-medium">
                {p.title}
              </TableHead>
              <TableCell>
                <span className="inline-flex items-center gap-1.5 text-sm">
                  <span
                    aria-hidden="true"
                    className={`size-2 rounded-full ${STATE[p.state].dot}`}
                  />
                  {STATE[p.state].text}
                </span>
              </TableCell>
              <TableCell className="whitespace-normal">
                {where(p, keys.providers)}
                {p.state === "bad" && p.said ? (
                  <span className="block text-muted-foreground text-xs">{p.said}</span>
                ) : null}
              </TableCell>
              <TableCell className="text-end">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!keys.can_save}
                  aria-label={`${p.state === "here" ? "Use my key for" : "Change"} ${p.title}`}
                  onClick={() => setOpen(p.id)}
                >
                  {p.state === "here" ? "Use my key" : p.state === "bad" ? "Fix" : "Change"}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {editing ? (
        <EditKey
          key={editing.id}
          api={api}
          product={editing}
          all={keys}
          onDone={(next) => {
            setKeys(next);
            setOpen(null);
            changed();
          }}
          onChanged={(next) => {
            setKeys(next);
            changed();
          }}
          onCancel={() => setOpen(null)}
        />
      ) : null}
    </section>
  );
}

function EditKey({
  api,
  product,
  all,
  onDone,
  onChanged,
  onCancel,
}: {
  api: OwnKeysApi;
  product: KeyProduct;
  all: OwnKeys;
  onDone: (keys: OwnKeys) => void;
  onChanged: (keys: OwnKeys) => void;
  onCancel: () => void;
}) {
  const providers = all.providers.filter((v) => v.kind === product.kind);
  const [mode, setMode] = useState<"here" | "key">(product.mode === "here" ? "key" : product.mode);
  const [provider, setProvider] = useState(product.provider ?? providers[0]?.id ?? "");
  const chosen = providers.find((v) => v.id === provider);
  const suggestions = product.kind === "text" ? (chosen?.models ?? []) : product.models;
  const [model, setModel] = useState(product.model ?? suggestions[0] ?? "");
  const [base, setBase] = useState(product.base_url ?? "");
  const [key, setKey] = useState("");
  const [tried, setTried] = useState<KeyTest | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const ids = { provider: useId(), model: useId(), base: useId(), key: useId(), list: useId() };
  const sameKind = all.products.filter(
    (p) => p.id !== product.id && p.kind === product.kind && p.key_saved,
  );
  const choice = {
    provider,
    model: model.trim(),
    ...(chosen?.needs_base ? { base_url: base.trim() } : {}),
    ...(key.trim() ? { key: key.trim() } : {}),
  };
  const ready = mode === "here" || (provider && model.trim() && (key.trim() || product.key_saved));

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
      className="grid gap-3 rounded-xl border bg-muted/40 p-4"
      aria-label={`${product.title}: where it runs`}
    >
      <h4 className="m-0 font-semibold text-sm">{product.title}</h4>
      <Segmented
        label={`Where ${product.title} runs`}
        value={mode}
        onValueChange={(v) => {
          setMode(v as "here" | "key");
          setTried(null);
        }}
        options={[
          { value: "here", label: "On this computer" },
          { value: "key", label: "With my key" },
        ]}
      />
      {mode === "key" ? (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor={ids.provider}>Provider</Label>
              <Select
                id={ids.provider}
                value={provider || undefined}
                onValueChange={(v) => {
                  setProvider(v);
                  setTried(null);
                  if (product.kind === "text") {
                    setModel(providers.find((x) => x.id === v)?.models[0] ?? "");
                  }
                }}
                options={providers.map((v) => ({ value: v.id, label: v.title }))}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={ids.model}>Model</Label>
              <Input
                id={ids.model}
                list={ids.list}
                value={model}
                spellCheck={false}
                onChange={(e) => {
                  setModel(e.target.value);
                  setTried(null);
                }}
              />
              <datalist id={ids.list}>
                {suggestions.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={ids.key}>Key</Label>
              <Input
                id={ids.key}
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={key}
                placeholder={
                  product.key_saved
                    ? "A key is saved. Paste a new one to change it."
                    : "Paste your key"
                }
                onChange={(e) => {
                  setKey(e.target.value);
                  setTried(null);
                }}
              />
            </div>
          </div>
          {chosen?.needs_base ? (
            <div className="grid gap-1.5">
              <Label htmlFor={ids.base}>The server's address</Label>
              <Input
                id={ids.base}
                value={base}
                placeholder="https://my-server.example/v1"
                spellCheck={false}
                onChange={(e) => setBase(e.target.value)}
              />
            </div>
          ) : null}
          {sameKind.length ? (
            <div className="flex flex-wrap gap-3">
              {sameKind.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="text-primary text-sm underline-offset-4 hover:underline"
                  onClick={() =>
                    void run("save", async () => {
                      const next = await api.copy(product.id, p.id);
                      onChanged(next);
                      const copied = next.products.find((x) => x.id === product.id);
                      if (copied?.provider) setProvider(copied.provider);
                    })
                  }
                >
                  Use the same key as {p.title}
                </button>
              ))}
            </div>
          ) : null}
          <p className="m-0 text-muted-foreground text-xs">
            What you make with {product.title} is sent to {chosen?.host || "that server"} with this
            key. Their terms and prices apply.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!ready || busy !== null}
              onClick={() =>
                void run("test", async () => setTried(await api.test(product.id, choice)))
              }
            >
              {busy === "test" ? "Testing…" : "Test"}
            </Button>
            {tried ? (
              <output className={tried.ok ? "text-ok text-sm" : "text-destructive text-sm"}>
                {tried.ok
                  ? `It answered in ${tried.ms} ms. Nothing is saved yet.`
                  : (tried.said ?? "It did not work.")}
              </output>
            ) : null}
          </div>
        </>
      ) : (
        <p className="m-0 text-muted-foreground text-sm">
          {product.title} runs on this computer.
          {product.key_saved ? " Your key stays saved until you remove it." : ""}
        </p>
      )}
      {error ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          disabled={!ready || busy !== null}
          onClick={() =>
            void run("save", async () =>
              onDone(await api.save(product.id, mode, mode === "key" ? choice : {})),
            )
          }
        >
          {busy === "save" ? "Saving…" : "Save"}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        {product.key_saved ? (
          <Button
            type="button"
            variant="ghost"
            className="ms-auto text-destructive"
            onClick={() => setRemoving(true)}
          >
            Remove the key
          </Button>
        ) : null}
      </div>
      {removing ? (
        <ConfirmDialog
          title={`Remove the key for ${product.title}?`}
          message={`${product.title} goes back to running on this computer. The key is deleted from this computer's keychain.`}
          confirmLabel="Remove"
          onConfirm={() => {
            setRemoving(false);
            void run("save", async () => onDone(await api.remove(product.id)));
          }}
          onCancel={() => setRemoving(false)}
        />
      ) : null}
    </section>
  );
}
