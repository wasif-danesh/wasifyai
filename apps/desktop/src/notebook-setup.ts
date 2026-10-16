// SPDX-License-Identifier: AGPL-3.0-only
// What a notebook needs on this computer: the search model (a catalogue model, fetched through the
// engine's model downloads) and the document reader (set up by the notebooks product). Both are
// asked for with their size and fetched only on a click; this turns what the engine says into the
// items the setup card shows.
import type { NotebooksStatus } from "@wasifyai/client";
import type { SetupItem } from "@wasifyai/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { modelsApi, notebooksApi } from "./api";
import { type DownloadState, type ModelEntry, downloadFraction } from "./models";

/** The id of the search model in the notebooks product's `models.yaml`. */
export const SEARCH_MODEL = "bge-small-en-v1.5";

export function setupItems(
  status: NotebooksStatus | null,
  entry: ModelEntry | null,
  download: DownloadState | null,
  problem: { id: SetupItem["id"]; message: string } | null,
): SetupItem[] {
  if (!status) return [];
  const items: SetupItem[] = [];

  const searchBytes = entry?.bytes_total ?? status.embedder.size_bytes;
  const running = download && download.entry_id === SEARCH_MODEL && download.status === "running";
  items.push({
    id: "search",
    title: "Search model",
    why: "Finds the passages of your documents that answer a question. Runs on this computer.",
    bytes: searchBytes,
    required: true,
    state: status.embedder.ready
      ? "ready"
      : running
        ? "working"
        : problem?.id === "search" ||
            (download?.entry_id === SEARCH_MODEL && download.status === "failed")
          ? "failed"
          : "missing",
    fraction: running && download ? downloadFraction(download) : undefined,
    message:
      problem?.id === "search"
        ? problem.message
        : download?.status === "failed"
          ? download.error
          : running
            ? "Downloading"
            : undefined,
  });

  const setup = status.reader.setup;
  if (setup.available) {
    const p = setup.progress;
    const installing = p.state === "installing";
    items.push({
      id: "reader",
      title: "Document reader",
      why: "Reads PDF, Word, PowerPoint, Excel files and pictures of text. Plain text, Markdown, CSV and HTML need nothing.",
      bytes: setup.offer.size_bytes,
      required: false,
      state: status.reader.ready
        ? "ready"
        : installing
          ? "working"
          : p.state === "failed" || problem?.id === "reader"
            ? "failed"
            : "missing",
      fraction: installing && p.total_bytes > 0 ? p.done_bytes / p.total_bytes : undefined,
      message: problem?.id === "reader" ? problem.message : p.message || undefined,
    });
  } else if (!status.reader.ready) {
    items.push({
      id: "reader",
      title: "Document reader",
      why: "Reads PDF, Word, PowerPoint, Excel files and pictures of text.",
      bytes: 0,
      required: false,
      state: "unavailable",
      message: setup.message || "Not available in this build.",
    });
  }
  return items;
}

/**
 * The status of the notebooks product and of the search model's download, kept fresh while something
 * is being set up, and the two actions that start a setup.
 */
export function useNotebookSetup() {
  const [status, setStatus] = useState<NotebooksStatus | null>(null);
  const [entry, setEntry] = useState<ModelEntry | null>(null);
  const [download, setDownload] = useState<DownloadState | null>(null);
  const [problem, setProblem] = useState<{ id: SetupItem["id"]; message: string } | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [s, overview] = await Promise.all([notebooksApi.status(), modelsApi.overview()]);
      if (!alive.current) return;
      setStatus(s);
      setEntry(overview.models.find((m) => m.id === SEARCH_MODEL) ?? null);
      setDownload(overview.download);
    } catch {
      // the engine is not answering: the screens show their own notices
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => {
      alive.current = false;
    };
  }, [refresh]);

  const working =
    (download?.entry_id === SEARCH_MODEL && download.status === "running") ||
    (status?.reader.setup.available === true &&
      status.reader.setup.progress.state === "installing");
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => void refresh(), 1000);
    return () => clearInterval(t);
  }, [working, refresh]);

  const start = useCallback(
    async (id: SetupItem["id"]) => {
      setProblem(null);
      try {
        if (id === "search") {
          if (!entry) throw new Error("The search model is not listed in this build.");
          setDownload(await modelsApi.start(entry));
        } else if (status?.reader.setup.available) {
          await notebooksApi.setupReader(status.reader.setup.offer.size_bytes);
        }
      } catch (e) {
        setProblem({ id, message: e instanceof Error ? e.message : "That did not start." });
      }
      await refresh();
    },
    [entry, status, refresh],
  );

  return {
    status,
    items: setupItems(status, entry, download, problem),
    searchReady: status?.embedder.ready ?? false,
    start,
    refresh,
  };
}
