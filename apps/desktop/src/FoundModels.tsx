// SPDX-License-Identifier: AGPL-3.0-only
import { Button, Notice, cn } from "@wasifyai/ui";
import { useCallback, useEffect, useState } from "react";
import { FitBadge } from "./FitBadge";
import { discoveryApi } from "./api";
import {
  type DiscoveryState,
  type FoundModel,
  STATE_LABEL,
  detailOf,
  groupFound,
} from "./discovery";
import { humanBytes } from "./engine";

const TONE = {
  ready: "border-ok/40 text-ok",
  can_use: "border-primary/50 text-primary",
  later: "text-muted-foreground",
  unsupported: "text-muted-foreground opacity-70",
} as const;

function ago(seconds: number | null): string {
  if (!seconds) return "not yet";
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} minutes ago`;
  if (s < 129_600) return `${Math.round(s / 3600)} hours ago`;
  return new Date(seconds * 1000).toLocaleDateString();
}

/** What other tools left on this computer: language, image and video models, LoRAs and their parts. Found
 * in known folders only (ADR-0063), listed where they are, never copied or changed. */
export function FoundModels({ onChanged }: { onChanged?: () => void }) {
  const [state, setState] = useState<DiscoveryState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setState(await discoveryApi.state());
    } catch (e) {
      setError(e instanceof Error ? e.message : "The list could not be read.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // while a scan runs (it starts by itself shortly after the app does), look again every second
  const running = state?.running ?? false;
  const first = state?.enabled && state.scanned_at === null;
  useEffect(() => {
    if (!running && !first) return;
    const began = Date.now();
    const t = setInterval(() => {
      if (Date.now() - began > 120_000)
        clearInterval(t); // never poll for ever
      else void refresh();
    }, 1000);
    return () => clearInterval(t);
  }, [running, first, refresh]);

  async function scanNow() {
    setError(null);
    try {
      await discoveryApi.scan();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The scan could not start.");
    }
  }

  async function use(m: FoundModel) {
    setBusy(m.id);
    setError(null);
    try {
      await discoveryApi.use(m.id);
      onChanged?.();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy(null);
    }
  }

  async function addFolder(folder: string) {
    if (!state) return;
    setError(null);
    try {
      setState(await discoveryApi.settings(state.enabled, [...state.folders, folder]));
    } catch (e) {
      setError(e instanceof Error ? e.message : "That folder could not be added.");
    }
  }

  if (!state) {
    return error ? (
      <Notice tone="error" title="That did not work">
        {error}
      </Notice>
    ) : null;
  }

  const groups = groupFound(state.items);

  return (
    <section className="grid gap-4" aria-label="Found on this computer">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-semibold text-lg">Found on this computer</h2>
          <p className="text-muted-foreground text-sm">
            {state.enabled
              ? running
                ? "Looking in the folders other tools use…"
                : `Looked ${ago(state.scanned_at)} in ${state.scanned.length} known ${
                    state.scanned.length === 1 ? "place" : "places"
                  }. Nothing is copied or changed.`
              : "Looking is turned off. You can turn it on in Settings."}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={running}
          onClick={() => void scanNow()}
        >
          {running ? "Looking…" : "Look again"}
        </Button>
      </div>

      {error ? (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      ) : null}

      {state.servers.length > 0 ? (
        <Notice tone="info" title="Running on this computer">
          {state.servers.map((s) => s.title).join(", ")} {state.servers.length === 1 ? "is" : "are"}{" "}
          running. The app can use {state.servers.length === 1 ? "it" : "them"} as a provider once
          that stage arrives; nothing is started or changed.
        </Notice>
      ) : null}

      {state.suggested.map((s) => (
        <div
          key={s.folder}
          className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm"
        >
          <span className="min-w-0 flex-1">
            <span className="font-medium">{s.tool}</span> keeps models in{" "}
            <span className="font-mono">{s.folder}</span>. macOS asks before an app may read that
            folder, so it is only looked at if you add it.
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void addFolder(s.folder)}
          >
            Look in this folder
          </Button>
        </div>
      ))}

      {state.truncated ? (
        <p className="text-muted-foreground text-sm">
          The list is cut short: the folders hold more files than one look covers.
        </p>
      ) : null}

      {groups.length === 0 && state.scanned_at !== null && !running ? (
        <p className="text-muted-foreground text-sm">
          No models from other tools were found in the known places.
        </p>
      ) : null}

      {groups.map((g) => (
        <div key={g.title} className="grid gap-2">
          <h3 className="font-medium text-sm">
            {g.title} <span className="text-muted-foreground">({g.items.length})</span>
          </h3>
          <ul className="grid gap-2">
            {g.items.map((m) => (
              <li key={m.id} className="grid gap-1 rounded-lg border p-3">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="min-w-0 flex-1 truncate font-medium" title={m.path}>
                    {m.name}
                  </span>
                  <span className="text-muted-foreground text-xs">{humanBytes(m.size)}</span>
                  <span className={cn("rounded-full border px-2 py-0.5 text-xs", TONE[m.state])}>
                    {STATE_LABEL[m.state]}
                  </span>
                  {m.state === "can_use" && m.use === "folder" ? (
                    <Button
                      type="button"
                      size="sm"
                      disabled={busy === m.id}
                      onClick={() => void use(m)}
                    >
                      Use it
                    </Button>
                  ) : null}
                </div>
                <p className="text-muted-foreground text-xs">
                  Found in {m.tool_title}
                  {detailOf(m) ? ` · ${detailOf(m)}` : ""}
                  {m.licence ? ` · ${m.licence}` : ""}
                </p>
                {m.fit ? <FitBadge fit={m.fit} /> : null}
                {m.reason ? <p className="text-sm">{m.reason}</p> : null}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
