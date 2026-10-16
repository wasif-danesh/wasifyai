"use client";

import type { NotebookFolder, NotebookSource, NotebooksApi, UploadResult } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

const POLL_MS = 1500;

function describe(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

export const reading = (s: NotebookSource) => s.status === "pending" || s.status === "processing";

export type UseNotebookSourcesOptions = {
  api: NotebooksApi;
  /** null while the notebook is a draft that has not been saved */
  notebookId: string | null;
  /** Called when something is added to a draft: save the notebook and give back its id. */
  ensureNotebook: () => Promise<string>;
};

/**
 * The sources and folders of one notebook, kept fresh: read again every 1.5 s while any source is
 * being read (the engine has no push stream for this, by design), and after each change made here.
 */
export function useNotebookSources({ api, notebookId, ensureNotebook }: UseNotebookSourcesOptions) {
  const [sources, setSources] = useState<NotebookSource[]>([]);
  const [folders, setFolders] = useState<NotebookFolder[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [rejected, setRejected] = useState<UploadResult["rejected"]>([]);
  const [busy, setBusy] = useState(false);
  const id = useRef(notebookId);
  id.current = notebookId;

  const refresh = useCallback(
    async (nid?: string) => {
      const target = nid ?? id.current;
      if (!target) return;
      try {
        const [s, f] = await Promise.all([api.sources(target), api.folders(target)]);
        if (target !== id.current && nid === undefined) return;
        setSources(s);
        setFolders(f);
        setLoaded(true);
      } catch (e) {
        setProblem(describe(e, "The sources could not be read."));
      }
    },
    [api],
  );

  useEffect(() => {
    setSources([]);
    setFolders([]);
    setLoaded(notebookId === null);
    if (notebookId) void refresh(notebookId);
  }, [notebookId, refresh]);

  const anyReading = sources.some(reading);
  useEffect(() => {
    if (!anyReading || !notebookId) return;
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [anyReading, notebookId, refresh]);

  async function guard<T>(fn: (nid: string) => Promise<T>, fallback: string): Promise<T | null> {
    setProblem(null);
    setBusy(true);
    try {
      const nid = id.current ?? (await ensureNotebook());
      const out = await fn(nid);
      await refresh(nid);
      return out;
    } catch (e) {
      setProblem(describe(e, fallback));
      return null;
    } finally {
      setBusy(false);
    }
  }

  return {
    sources,
    folders,
    loaded,
    problem,
    rejected,
    busy,
    clearProblem: () => {
      setProblem(null);
      setRejected([]);
    },
    refresh: () => refresh(),
    async upload(files: File[], folderId?: string | null) {
      const out = await guard(
        (nid) => api.upload(nid, files, folderId),
        "The files could not be added.",
      );
      if (out) setRejected(out.rejected);
      return out;
    },
    addNote: (title: string, content: string, folderId?: string | null) =>
      guard((nid) => api.addNote(nid, title, content, folderId), "The note could not be added."),
    rename: (sid: string, title: string) =>
      guard((nid) => api.renameSource(nid, sid, title), "The name could not be changed."),
    remove: (sid: string) =>
      guard((nid) => api.removeSource(nid, sid), "The source could not be removed."),
    retry: (sid: string) => guard((nid) => api.retry(nid, sid), "It could not be read again."),
    cancel: (sid: string) => guard((nid) => api.cancel(nid, sid), "It could not be stopped."),
    move: (ids: string[], folderId: string | null) =>
      guard((nid) => api.move(nid, ids, folderId), "The source could not be moved."),
    createFolder: (name: string, parentId?: string | null) =>
      guard((nid) => api.createFolder(nid, name, parentId), "The folder could not be made."),
    renameFolder: (fid: string, name: string) =>
      guard((nid) => api.renameFolder(nid, fid, name), "The folder could not be renamed."),
    removeFolder: (fid: string) =>
      guard((nid) => api.removeFolder(nid, fid), "The folder could not be removed."),
  };
}
