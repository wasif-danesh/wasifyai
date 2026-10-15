// SPDX-License-Identifier: AGPL-3.0-only
import { Button, JobMeter, Notice, cn } from "@wasifyai/ui";
import { Download, Search } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { FitBadge } from "./FitBadge";
import { hubApi, modelsApi } from "./api";
import { humanBytes } from "./engine";
import {
  CAPABILITY_LABEL,
  type Capability,
  type HubModel,
  type HubResult,
  type HubState,
  type ShelfItem,
  type Sort,
  type Variant,
  ago,
  compactCount,
  paramsLabel,
} from "./hub";

const INPUT =
  "h-10 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";

function message(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong.";
}

/** Discover (ADR-0064): find open-weight models and get one. Hugging Face is contacted only after the
 * person agrees, and only by the engine. */
export function ModelHub({ onDownloaded }: { onDownloaded?: () => void }) {
  const [state, setState] = useState<HubState | null>(null);
  const [query, setQuery] = useState("");
  const [capability, setCapability] = useState<Capability>("language");
  const [sort, setSort] = useState<Sort>("downloads");
  const [results, setResults] = useState<HubResult[] | null>(null);
  const [stale, setStale] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    hubApi
      .state()
      .then(setState)
      .catch((e) => setError(message(e)));
  }, []);

  const search = useCallback(async (q: string, cap: Capability, by: Sort) => {
    setBusy(true);
    setError(null);
    try {
      const out = await hubApi.search(q, cap, by);
      setResults(out.items);
      setStale(out.stale);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }, []);

  async function agree() {
    try {
      await hubApi.setEnabled(true);
      setState((s) => (s ? { ...s, enabled: true } : s));
      setAsking(false);
      void search(query, capability, sort);
    } catch (e) {
      setError(message(e));
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!state?.enabled) {
      setAsking(true);
      return;
    }
    void search(query, capability, sort);
  }

  function openRepo(repo: string) {
    if (!state?.enabled) {
      setAsking(true);
      return;
    }
    setOpen(repo);
  }

  if (!state) {
    return error ? (
      <Notice tone="error" title="Discover is not available">
        {error}
      </Notice>
    ) : null;
  }

  return (
    <section className="grid gap-4" aria-label="Discover models">
      {!state.enabled || asking ? (
        <Notice
          title="Browsing models contacts Hugging Face"
          actions={
            <>
              <Button type="button" onClick={() => void agree()}>
                Turn on browsing
              </Button>
              <Button type="button" variant="outline" onClick={() => setAsking(false)}>
                Not now
              </Button>
            </>
          }
        >
          To find models, the app asks huggingface.co for lists of open models. It sends the words
          you search for and the names of the models you open, with no account and nothing that
          identifies you. Files are fetched only after you confirm them, and you can turn browsing
          off in Settings. The recommended list below works without it.
        </Notice>
      ) : null}

      {error ? (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      ) : null}

      <form className="flex flex-wrap items-center gap-2" onSubmit={onSubmit}>
        <label className="relative min-w-48 flex-1">
          <span className="sr-only">Search models</span>
          <Search className="-translate-y-1/2 absolute start-3 top-1/2 size-4 text-muted-foreground" />
          <input
            type="search"
            className={cn(INPUT, "w-full ps-9")}
            placeholder="Search open models, for example qwen3 or llama"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          aria-label="Kind of model"
          className={INPUT}
          value={capability}
          onChange={(e) => setCapability(e.target.value as Capability)}
        >
          {state.capabilities.map((c) => (
            <option key={c} value={c}>
              {CAPABILITY_LABEL[c]}
            </option>
          ))}
        </select>
        <select
          aria-label="Sort by"
          className={INPUT}
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
        >
          <option value="downloads">Most downloaded</option>
          <option value="likes">Most liked</option>
          <option value="recent">Recently updated</option>
        </select>
        <Button type="submit" disabled={busy}>
          {busy ? "Searching…" : "Search"}
        </Button>
      </form>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <div className="grid content-start gap-2">
          {results === null ? (
            <Shelf shelf={state.shelf} onOpen={openRepo} />
          ) : results.length === 0 ? (
            <p className="text-muted-foreground text-sm">Nothing matched. Try other words.</p>
          ) : (
            <>
              {stale ? (
                <p className="text-muted-foreground text-xs">
                  Hugging Face could not be reached: this is the last list.
                </p>
              ) : null}
              <ul className="grid gap-2" aria-label="Results">
                {results.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      aria-pressed={open === r.id}
                      className={cn(
                        "grid w-full gap-1 rounded-lg border p-3 text-start outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                        open === r.id && "border-primary bg-accent",
                      )}
                      onClick={() => openRepo(r.id)}
                    >
                      <span className="truncate font-medium">{r.name}</span>
                      <span className="flex flex-wrap items-center gap-x-3 text-muted-foreground text-xs">
                        <span>{r.publisher}</span>
                        <span>{compactCount(r.downloads)} downloads</span>
                        <span>{compactCount(r.likes)} likes</span>
                        <span>{ago(r.updated)}</span>
                        {r.license ? <span>{r.license}</span> : null}
                        {r.gated ? <span className="text-warn">needs an account</span> : null}
                        {!r.runnable ? <span>view only</span> : null}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        <div className="min-w-0">
          {open ? (
            <ModelDetail key={open} repo={open} onDownloaded={onDownloaded} />
          ) : (
            <p className="rounded-lg border border-dashed p-6 text-center text-muted-foreground text-sm">
              Choose a model to see its files, what it needs and what it is for.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function Shelf({ shelf, onOpen }: { shelf: ShelfItem[]; onOpen: (repo: string) => void }) {
  return (
    <div className="grid gap-2">
      <h3 className="font-medium text-sm">Recommended to start with</h3>
      <ul className="grid gap-2">
        {shelf.map((m) => (
          <li key={m.repo}>
            <button
              type="button"
              className="grid w-full gap-1 rounded-lg border p-3 text-start outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => onOpen(m.repo)}
            >
              <span className="flex items-center gap-2 font-medium">
                {m.title}
                {m.recommended ? (
                  <span className="rounded-full border border-primary/50 px-2 py-0.5 font-normal text-primary text-xs">
                    Recommended
                  </span>
                ) : null}
              </span>
              <span className="text-muted-foreground text-xs">{m.note}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ModelDetail({ repo, onDownloaded }: { repo: string; onDownloaded?: () => void }) {
  const [model, setModel] = useState<HubModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [card, setCard] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<Variant | null>(null);
  const [insist, setInsist] = useState(false);
  const [diskFree, setDiskFree] = useState<number | null>(null);
  const [download, setDownload] = useState<{ id: string; total: number } | null>(null);
  const [progress, setProgress] = useState<{ done: number; status: string; error: string } | null>(
    null,
  );

  useEffect(() => {
    let gone = false;
    hubApi
      .model(repo)
      .then((m) => !gone && setModel(m))
      .catch((e) => !gone && setError(message(e)));
    modelsApi
      .overview()
      .then((o) => !gone && setDiskFree(o.disk_free_bytes))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [repo]);

  // follow a running download every second until it ends
  useEffect(() => {
    if (!download) return;
    let gone = false;
    const t = setInterval(async () => {
      try {
        const d = await modelsApi.download(download.id);
        if (gone) return;
        setProgress({ done: d.bytes_done, status: d.status, error: d.error });
        if (d.status !== "running") {
          clearInterval(t);
          if (d.status === "done") onDownloaded?.();
        }
      } catch {
        // try again on the next tick
      }
    }, 1000);
    return () => {
      gone = true;
      clearInterval(t);
    };
  }, [download, onDownloaded]);

  async function start(v: Variant) {
    setError(null);
    try {
      const d = await hubApi.download(repo, v, insist);
      setConfirming(null);
      setInsist(false);
      setDownload({ id: d.id, total: d.bytes_total });
      setProgress({ done: 0, status: "running", error: "" });
    } catch (e) {
      setError(message(e));
    }
  }

  if (!model) {
    return error ? (
      <Notice tone="error" title="This model could not be shown">
        {error}
      </Notice>
    ) : (
      <p className="text-muted-foreground text-sm">Looking…</p>
    );
  }

  const busy = progress?.status === "running";
  return (
    <article className="grid gap-4 rounded-lg border p-4" aria-label={model.id}>
      <header className="grid gap-1">
        <h3 className="break-words font-semibold text-lg">{model.id}</h3>
        <p className="flex flex-wrap gap-x-3 text-muted-foreground text-xs">
          <span>{compactCount(model.downloads)} downloads</span>
          <span>{compactCount(model.likes)} likes</span>
          <span>updated {ago(model.updated)}</span>
          {model.architecture ? <span>{model.architecture}</span> : null}
          {model.parameters ? <span>{paramsLabel(model.parameters)} parameters</span> : null}
          {model.context_length ? <span>{compactCount(model.context_length)} context</span> : null}
        </p>
        <p className="text-sm">
          Licence: <span className="font-medium">{model.license || "not stated"}</span>
          {model.gated ? " · needs a Hugging Face account that accepted its terms" : ""}
        </p>
      </header>

      {error ? (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      ) : null}

      {model.stale ? (
        <p className="text-muted-foreground text-xs">Shown from the last time it was reached.</p>
      ) : null}

      {!model.runnable ? (
        <Notice title="View only">
          This app cannot run this kind of model yet, so there is nothing to get. Language and
          embedding models in GGUF form can be run.
        </Notice>
      ) : (
        <>
          {!model.has_chat_template && model.capability === "language" ? (
            <Notice tone="warn" title="No chat template in the file">
              Answers from this model may look odd, because the file does not carry its own chat
              template.
            </Notice>
          ) : null}
          <ul className="grid gap-2" aria-label="Files">
            {model.variants.map((v) => (
              <li
                key={v.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border p-2"
              >
                <span className="min-w-0 flex-1 truncate text-sm" title={v.files.join(", ")}>
                  {v.name}
                  {v.files.length > 1 ? ` (${v.files.length} parts)` : ""}
                </span>
                {v.quant ? <span className="text-muted-foreground text-xs">{v.quant}</span> : null}
                <span className="text-muted-foreground text-xs">{humanBytes(v.size)}</span>
                {v.fit ? <FitBadge fit={v.fit} /> : null}
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || model.gated}
                  onClick={() => {
                    setConfirming(v);
                    setInsist(false);
                  }}
                >
                  <Download className="size-4" /> Get
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}

      {confirming ? (
        <div className="grid gap-3 rounded-md border bg-surface p-3">
          <p className="font-semibold">Get these files?</p>
          <ul className="grid gap-1 text-sm">
            {confirming.files.map((f, i) => (
              <li key={f} className="flex justify-between gap-3">
                <span className="truncate">{f}</span>
                <span className="tabular-nums">{humanBytes(confirming.sizes[i] ?? 0)}</span>
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground text-sm">
            {humanBytes(confirming.size)} from huggingface.co/{model.id}. Licence:{" "}
            {model.license || "not stated"}.
            {diskFree !== null ? ` Free space on that drive: ${humanBytes(diskFree)}.` : ""} The
            files are checked against their published checksums.
          </p>
          {confirming.fit?.verdict === "too_big" ? (
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={insist}
                onChange={(e) => setInsist(e.target.checked)}
              />
              <span>
                I know it will not run on this computer. Get the files anyway (for another
                computer).
              </span>
            </label>
          ) : null}
          <div className="flex gap-2">
            <Button
              type="button"
              disabled={confirming.fit?.verdict === "too_big" && !insist}
              onClick={() => void start(confirming)}
            >
              Get {humanBytes(confirming.size)}
            </Button>
            <Button type="button" variant="outline" onClick={() => setConfirming(null)}>
              Not now
            </Button>
          </div>
        </div>
      ) : null}

      {progress ? (
        <div className="grid gap-2">
          {progress.status === "running" && download ? (
            <JobMeter
              title="Getting the model"
              text={`${humanBytes(progress.done)} of ${humanBytes(download.total)}`}
              value={download.total ? progress.done / download.total : 0}
              label="Model download progress"
            />
          ) : null}
          {progress.status === "done" ? (
            <Notice tone="ok" title="The model is on this computer">
              Find it under On device, then choose it for chat.
            </Notice>
          ) : null}
          {progress.status === "failed" ? (
            <Notice tone="error" title="The download stopped">
              {progress.error}
            </Notice>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-2">
        <button
          type="button"
          className="justify-self-start text-sm underline underline-offset-4"
          aria-expanded={card !== null}
          onClick={() => {
            if (card !== null) {
              setCard(null);
              return;
            }
            setCard("");
            hubApi
              .readme(repo)
              .then((r) => setCard(r.text || "This model has no description."))
              .catch((e) => setCard(message(e)));
          }}
        >
          Model card
        </button>
        {card !== null ? (
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border p-3 text-xs">
            {card || "Looking…"}
          </pre>
        ) : null}
      </div>
    </article>
  );
}
