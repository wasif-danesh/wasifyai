"use client";

import { type ReactNode, createContext, useCallback, useContext, useMemo, useState } from "react";
import { type DownloadManager, DownloadTray, useDownloadManager } from "./downloads";
import type { ChoicesApi, GroupId } from "./types";

/** What gives a group's picker its rows and work: the app window (the web has hosted models and no picker). */
export type ChoicesSource = (group: GroupId, task?: string) => ChoicesApi | null;

type Context = {
  source: ChoicesSource;
  version: number;
  bump: () => void;
  downloads: DownloadManager;
};

const ModelChoicesContext = createContext<Context | null>(null);

/**
 * Turns the picker on for every screen under it (ADR-0086). `version` changes whenever a model is chosen or
 * downloaded, so a screen that lists models (the voice screens) reads them again by itself.
 */
export function ModelChoicesProvider({
  source,
  children,
}: {
  source: ChoicesSource;
  children: ReactNode;
}) {
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  const downloads = useDownloadManager(bump);
  const value = useMemo(
    () => ({ source, version, bump, downloads }),
    [source, version, bump, downloads],
  );
  return (
    <ModelChoicesContext.Provider value={value}>
      {children}
      <DownloadTray manager={downloads} />
    </ModelChoicesContext.Provider>
  );
}

/** The picker's rows and work for a group, or null where there is no picker (the web). */
export function useChoicesFor(group: GroupId, task?: string): ChoicesApi | null {
  const ctx = useContext(ModelChoicesContext);
  const source = ctx?.source;
  // one object per group and task while the source is the same, so a screen re-rendering does not reload the rows
  return useMemo(() => source?.(group, task) ?? null, [source, group, task]);
}

/** A number that changes when a model is chosen or downloaded anywhere. */
export function useChoicesVersion(): number {
  return useContext(ModelChoicesContext)?.version ?? 0;
}

/** Tell every screen that the models changed. */
export function useChoicesChanged(): () => void {
  return useContext(ModelChoicesContext)?.bump ?? (() => {});
}

/** The downloads running in the background, for every screen (null where there is no provider, as in a small test). */
export function useDownloadsContext(): DownloadManager | null {
  return useContext(ModelChoicesContext)?.downloads ?? null;
}
