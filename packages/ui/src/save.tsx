"use client";

import { type ReactNode, createContext, useCallback, useContext } from "react";

/** A copy that was saved: its name, and where when the engine wrote it (the app window). */
export type Saved = { name: string; path?: string };

/**
 * What the app window can do that a web page cannot: ask the person where to save (the system's Save As
 * box) and write a file there. The window has no download handler, so a link with `download` saves
 * nothing in it. Absent on the web, where the browser saves files itself.
 */
export type SaveAs = {
  /** The full path the person chose, or null when they cancelled the box. */
  choose(suggestedName: string): Promise<string | null>;
  /** Write a file the window holds at a path the person chose. */
  write(path: string, data: Blob): Promise<Saved>;
};

const SaveAsContext = createContext<SaveAs | null>(null);

export function SaveAsProvider({ value, children }: { value: SaveAs | null; children: ReactNode }) {
  return <SaveAsContext.Provider value={value}>{children}</SaveAsContext.Provider>;
}

/** A file name from some words and an extension: letters, digits and hyphens, short, never empty. */
export function fileNameFor(words: string, ext: string, fallback = "file"): string {
  const stem =
    words
      .normalize("NFKD")
      .replace(/\p{M}/gu, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48)
      .replace(/-+$/g, "") || fallback;
  return ext ? `${stem}.${ext.replace(/^\./, "")}` : stem;
}

/** The extension of a file name or address (without a query), lower case, or a fallback. */
export function extensionOf(nameOrUrl: string, fallback: string): string {
  const clean = nameOrUrl.split(/[?#]/)[0] ?? "";
  const dot = clean.lastIndexOf(".");
  const ext = dot >= 0 ? clean.slice(dot + 1).toLowerCase() : "";
  return /^[a-z0-9]{1,5}$/.test(ext) ? ext : fallback;
}

/** "Saved as plan.docx in Downloads." (the folder only when it is known). */
export function savedText(saved: Saved): string {
  const parts = (saved.path ?? "").split(/[\\/]/).filter(Boolean);
  const folder = parts.length > 1 ? parts[parts.length - 2] : null;
  return folder ? `Saved as ${saved.name} in ${folder}.` : `Saved as ${saved.name}.`;
}

/** A file the browser saves (the web app), through a link that is clicked at once. */
function browserSave(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export type SaveOptions = {
  /** The name offered in the Save As box, and the browser's file name. */
  name: string;
  /** The engine copies a file it keeps: at the chosen path, or (no box available) into its export folder. */
  copy?: (path?: string) => Promise<Saved>;
  /** The file's bytes, for a window or a browser that holds them. */
  blob?: () => Promise<Blob>;
};

/**
 * "Save a copy", the same on every screen. In the app window it asks where to save and does nothing when
 * the person cancels (`null`); on the web the browser saves the file. Where there is no Save As box but the
 * engine keeps the file (a test, a development window), the engine's export folder is used.
 */
export function useSaveCopy(): (options: SaveOptions) => Promise<Saved | null> {
  const dialog = useContext(SaveAsContext);
  return useCallback(
    async ({ name, copy, blob }) => {
      if (dialog) {
        const path = await dialog.choose(name);
        if (!path) return null;
        if (copy) return copy(path);
        if (blob) return dialog.write(path, await blob());
        throw new Error("nothing to save");
      }
      if (copy) return copy();
      if (blob) {
        browserSave(await blob(), name);
        return { name };
      }
      throw new Error("nothing to save");
    },
    [dialog],
  );
}
