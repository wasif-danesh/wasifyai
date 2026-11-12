"use client";
// Admin › Media on the cloud-only web (ADR-0099; ADR-0100, stage CP11): the service's Runware, WaveSpeed and fal.ai
// keys, the same screen as the desktop's Settings › Your keys, and the cloud model each product runs on. Each job goes
// to the cheapest offer of that model with a key.
import { Notice } from "@/components/Notice";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { transport } from "@/lib/run-client";
import { muted, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import {
  type CloudModels,
  type KeyProduct,
  type OwnKeysApi,
  createOwnKeysApi,
} from "@wasifyai/client";
import { YourKeys } from "@wasifyai/ui";
import { useCallback, useEffect, useId, useMemo, useState } from "react";

export function ServiceKeys({ api: given }: { api?: OwnKeysApi }) {
  const api = useMemo(() => given ?? createOwnKeysApi(transport), [given]);
  // a key added or removed changes which models each product can run
  const [round, setRound] = useState(0);
  const keysApi = useMemo<OwnKeysApi>(() => {
    const after =
      <A extends unknown[], R>(fn: (...a: A) => Promise<R>) =>
      async (...a: A) => {
        const out = await fn(...a);
        setRound((n) => n + 1);
        return out;
      };
    return { ...api, save: after(api.save), remove: after(api.remove), check: after(api.check) };
  }, [api]);
  return (
    <div className="grid gap-8">
      <YourKeys api={keysApi} place="service" />
      <ServiceModels api={api} round={round} />
    </div>
  );
}

function ServiceModels({ api, round }: { api: OwnKeysApi; round: number }) {
  const [products, setProducts] = useState<KeyProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the round is the trigger
  useEffect(() => {
    api
      .list()
      .then((l) => setProducts(l.products.filter((p) => p.kind === "media" && p.id !== "media")))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not read them."));
  }, [api, round]);
  if (error) {
    return (
      <Notice tone="error" title="Couldn't load the models">
        {error}
      </Notice>
    );
  }
  if (!products) return null;
  return (
    <section aria-labelledby="service-models" className="grid gap-4">
      <h2 id="service-models" className="font-semibold text-lg">
        Models
      </h2>
      <p className={muted}>
        The cloud model each product runs on. Until you choose, it is the first one a key can run.
        Each job goes to the cheapest offer of the model with a key.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        {products.map((p) => (
          <ProductModel key={p.id} api={api} product={p} round={round} />
        ))}
      </div>
    </section>
  );
}

function ProductModel({
  api,
  product,
  round,
}: {
  api: OwnKeysApi;
  product: KeyProduct;
  round: number;
}) {
  const id = useId();
  const [list, setList] = useState<CloudModels | null>(null);
  const [chosen, setChosen] = useState<string | null>(product.use?.model ?? null);
  const [problem, setProblem] = useState<string | null>(null);
  const read = useCallback(
    () =>
      api
        .cloud(product.id)
        .then(setList)
        .catch(() => setList(null)),
    [api, product.id],
  );
  // biome-ignore lint/correctness/useExhaustiveDependencies: the round is the trigger
  useEffect(() => {
    void read();
  }, [read, round]);
  useEffect(() => setChosen(product.use?.model ?? null), [product.use?.model]);
  const models = list?.models ?? [];
  return (
    <div className={cn(panel, "grid gap-2")}>
      <Field>
        <FieldLabel htmlFor={id}>{product.title}</FieldLabel>
        {models.length ? (
          <Select
            value={chosen ?? undefined}
            onValueChange={(model) => {
              setProblem(null);
              setChosen(model);
              api
                .use(product.id, { model })
                .then(setList)
                .catch((e: unknown) => {
                  setProblem(e instanceof Error ? e.message : "That did not work.");
                  setChosen(product.use?.model ?? null);
                });
            }}
          >
            <SelectTrigger id={id} className="w-full">
              <SelectValue placeholder="Choose a model" />
            </SelectTrigger>
            <SelectContent>
              {models.map((m) => (
                <SelectItem key={m.model} value={m.model}>
                  {m.title} · {m.price}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <FieldDescription>No key can run a model for it yet: add one above.</FieldDescription>
        )}
        {problem ? (
          <FieldDescription className="text-destructive">{problem}</FieldDescription>
        ) : null}
      </Field>
    </div>
  );
}
