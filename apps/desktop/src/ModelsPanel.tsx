// SPDX-License-Identifier: AGPL-3.0-only
import { Button, JobMeter, Notice } from "@wasifyai/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { FitBadge } from "./FitBadge";
import { modelsApi } from "./api";
import { humanBytes } from "./engine";
import {
  type EngineInfo,
  type ModelEntry,
  type ModelsOverview,
  downloadFraction,
  missingFiles,
} from "./models";

const INPUT =
  "h-10 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";

function message(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong.";
}

/** The models the app can use: what is on this computer, getting a missing one (after a look at exactly
 * what will be fetched), where models are kept, and the loaded model. */
export function ModelsPanel() {
  const [overview, setOverview] = useState<ModelsOverview | null>(null);
  const [engine, setEngine] = useState<EngineInfo | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  // the person was told a model will not fit and chose to get its files anyway
  const [insist, setInsist] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelsDir, setModelsDir] = useState("");
  const [extraDirs, setExtraDirs] = useState("");
  const [foldersOpen, setFoldersOpen] = useState(false);
  const edited = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const [o, e] = await Promise.all([modelsApi.overview(), modelsApi.engine()]);
      setOverview(o);
      setEngine(e);
      if (!edited.current) {
        setModelsDir(o.folders.models_dir);
        setExtraDirs(o.folders.extra_dirs.join("\n"));
      }
    } catch (e) {
      setError(message(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // while a download runs, look again every second; otherwise every ten
  const downloading = overview?.download?.status === "running";
  useEffect(() => {
    const t = setInterval(() => void refresh(), downloading ? 1000 : 10_000);
    return () => clearInterval(t);
  }, [refresh, downloading]);

  if (!overview) {
    return error ? (
      <Notice tone="error" title="Models are not available">
        {error}
      </Notice>
    ) : null;
  }

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(message(e));
    }
    await refresh();
  };

  const dl = overview.download;
  return (
    <section className="grid gap-4" aria-label="Models">
      <h2 className="font-semibold text-lg">Models</h2>
      {error ? (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      ) : null}

      {overview.models.map((m: ModelEntry) => {
        const { files, bytes } = missingFiles(m);
        const mine = dl && dl.entry_id === m.id ? dl : null;
        return (
          <article key={m.id} className="grid gap-3 rounded-lg border p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-semibold">{m.title}</h3>
              <span className="text-muted-foreground text-sm">
                {m.status === "ready"
                  ? "On this computer"
                  : m.status === "partial"
                    ? `${humanBytes(m.bytes_missing)} still to get`
                    : `${humanBytes(m.bytes_total)} to get`}
              </span>
            </div>
            {m.note ? <p className="text-muted-foreground text-sm">{m.note}</p> : null}
            {m.fit ? <FitBadge fit={m.fit} /> : null}
            {m.fit && m.fit.verdict !== "fits" ? (
              <Notice
                tone={m.fit.verdict === "too_big" ? "error" : "warn"}
                title={m.fit.verdict === "too_big" ? "This will not fit" : "This computer is tight"}
              >
                {m.fit.reason}
              </Notice>
            ) : null}

            {mine && mine.status === "running" ? (
              <>
                <JobMeter
                  title={`Getting ${mine.current || "the model"}`}
                  text={`${humanBytes(mine.bytes_done)} of ${humanBytes(mine.bytes_total)}`}
                  value={downloadFraction(mine)}
                  label="Model download progress"
                />
                <div>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => act(() => modelsApi.cancel(mine.id))}
                  >
                    Cancel
                  </Button>
                </div>
              </>
            ) : null}
            {mine && mine.status === "failed" ? (
              <Notice tone="error" title="The download stopped">
                {mine.error}
              </Notice>
            ) : null}

            {confirming === m.id ? (
              <div className="grid gap-3 rounded-md border bg-surface p-3">
                <p className="font-semibold">Get these files?</p>
                <ul className="grid gap-1 text-sm">
                  {files.map((f) => (
                    <li key={f.name} className="flex justify-between gap-3">
                      <span className="truncate">{f.name}</span>
                      <span className="tabular-nums">{humanBytes(f.size)}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-muted-foreground text-sm">
                  {humanBytes(bytes)} from {m.source}. Licence: {m.licence}. Free space on that
                  drive: {humanBytes(overview.disk_free_bytes)}. The files are checked against their
                  published checksums.
                </p>
                {m.fit?.verdict === "too_big" ? (
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={insist}
                      onChange={(e) => setInsist(e.target.checked)}
                    />
                    <span>
                      I know it will not run on this computer. Get the files anyway (for another
                      computer, or this one after an upgrade).
                    </span>
                  </label>
                ) : null}
                <div className="flex gap-2">
                  <Button
                    type="button"
                    disabled={m.fit?.verdict === "too_big" && !insist}
                    onClick={() => {
                      setConfirming(null);
                      void act(() => modelsApi.start(m, insist));
                      setInsist(false);
                    }}
                  >
                    Get {humanBytes(bytes)}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setConfirming(null);
                      setInsist(false);
                    }}
                  >
                    Not now
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {m.status !== "ready" && !(mine && mine.status === "running") ? (
                  <Button
                    type="button"
                    onClick={() => setConfirming(m.id)}
                    disabled={!!dl && dl.status === "running"}
                  >
                    Get the model
                  </Button>
                ) : null}
                {m.files.some((f) => f.removable) && !(mine && mine.status === "running") ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => act(() => modelsApi.remove(m.id))}
                  >
                    Remove from the app's folder
                  </Button>
                ) : null}
              </div>
            )}
            <ul className="grid gap-0.5 text-muted-foreground text-xs">
              {m.files.map((f) => (
                <li key={f.name}>
                  {f.present ? "✓" : "·"} {f.name} ({humanBytes(f.size)})
                  {f.present && f.location ? `, in ${f.location}` : ""}
                </li>
              ))}
            </ul>
          </article>
        );
      })}

      {engine ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-muted-foreground">
            Image engine:{" "}
            {!engine.image_engine_installed
              ? "not set up"
              : engine.model_loaded
                ? engine.busy
                  ? "making an image"
                  : "model loaded in memory"
                : engine.image_engine_running
                  ? "running, no model loaded"
                  : "ready, not started"}
          </span>
          {engine.model_loaded && !engine.busy ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => act(() => modelsApi.unload())}
            >
              Unload model
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-2">
        <button
          type="button"
          className="justify-self-start text-sm underline underline-offset-4"
          onClick={() => setFoldersOpen((v) => !v)}
          aria-expanded={foldersOpen}
        >
          Where models are kept
        </button>
        {foldersOpen ? (
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              edited.current = false;
              void act(() =>
                modelsApi.setFolders(
                  modelsDir.trim() || null,
                  extraDirs
                    .split("\n")
                    .map((p) => p.trim())
                    .filter(Boolean),
                ),
              );
            }}
          >
            <label className="grid gap-1 text-sm">
              The app's own models folder (new downloads go here)
              <input
                className={INPUT}
                value={modelsDir}
                onChange={(e) => {
                  edited.current = true;
                  setModelsDir(e.target.value);
                }}
              />
            </label>
            <label className="grid gap-1 text-sm">
              Other folders the app may read, one per line (it never writes to them)
              <textarea
                className={`${INPUT} min-h-20 py-2`}
                value={extraDirs}
                onChange={(e) => {
                  edited.current = true;
                  setExtraDirs(e.target.value);
                }}
              />
            </label>
            <div>
              <Button type="submit" size="sm">
                Save folders
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </section>
  );
}
