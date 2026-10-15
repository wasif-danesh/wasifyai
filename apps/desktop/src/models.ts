// SPDX-License-Identifier: AGPL-3.0-only
// The engine's model routes (`/desktop/...`, services/api/src/wasifyai_api/desktop_models.py): what the
// catalogue offers, what is on this computer, and getting a missing model.
import type { Transport } from "@wasifyai/client";
import { HttpError } from "@wasifyai/client";

export type ModelFile = {
  folder: string;
  name: string;
  size: number;
  present: boolean;
  location: string | null;
  removable: boolean;
  partial_bytes: number;
};

export type ModelEntry = {
  id: string;
  title: string;
  licence: string;
  source: string;
  note: string;
  approx_ram_gb: number;
  status: "ready" | "partial" | "missing";
  files: ModelFile[];
  bytes_total: number;
  bytes_missing: number;
  memory_warning: string | null;
};

export type DownloadState = {
  id: string;
  entry_id: string;
  files: string[];
  bytes_total: number;
  bytes_done: number;
  status: "running" | "done" | "failed" | "cancelled";
  current: string;
  error: string;
};

export type ModelsOverview = {
  models: ModelEntry[];
  folders: { models_dir: string; extra_dirs: string[] };
  memory_bytes: number | null;
  disk_free_bytes: number;
  download: DownloadState | null;
};

export type EngineInfo = {
  image_engine_installed: boolean;
  image_engine_running: boolean;
  model_loaded: boolean;
  busy: boolean;
};

/** The files a download would fetch, and the total: exactly what the confirmation shows and echoes. */
export function missingFiles(e: ModelEntry): { files: ModelFile[]; bytes: number } {
  const files = e.files.filter((f) => !f.present);
  return { files, bytes: files.reduce((n, f) => n + f.size, 0) };
}

/** What the engine requires back with a download request. */
export function confirmationFor(e: ModelEntry): { files: string[]; bytes: number } {
  const { files, bytes } = missingFiles(e);
  return { files: files.map((f) => f.name), bytes };
}

/** 0 to 1 */
export function downloadFraction(d: DownloadState): number {
  return d.bytes_total > 0 ? Math.min(1, Math.max(0, d.bytes_done / d.bytes_total)) : 0;
}

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

const JSON_HEADERS = { "content-type": "application/json" };

export function createModelsApi(transport: Transport) {
  return {
    overview: () => json<ModelsOverview>(transport, "/desktop/models"),
    download: (id: string) => json<DownloadState>(transport, `/desktop/downloads/${id}`),
    start: (entry: ModelEntry) =>
      json<DownloadState>(transport, `/desktop/models/${entry.id}/download`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(confirmationFor(entry)),
      }),
    cancel: (id: string) =>
      json<{ cancelled: boolean }>(transport, `/desktop/downloads/${id}/cancel`, {
        method: "POST",
      }),
    remove: (entryId: string) =>
      json<{ removed: number }>(transport, `/desktop/models/${entryId}`, { method: "DELETE" }),
    setFolders: (modelsDir: string | null, extraDirs: string[]) =>
      json<{ models_dir: string; extra_dirs: string[] }>(transport, "/desktop/models/folders", {
        method: "PUT",
        headers: JSON_HEADERS,
        body: JSON.stringify({ models_dir: modelsDir, extra_dirs: extraDirs }),
      }),
    engine: () => json<EngineInfo>(transport, "/desktop/engine"),
    unload: () =>
      json<{ unloaded: boolean }>(transport, "/desktop/engine/unload", { method: "POST" }),
  };
}

export type ModelsApi = ReturnType<typeof createModelsApi>;
