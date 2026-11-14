"use client";
// The Files tab of a coding session (mockup `files`): the project's folders as a tree, opened a folder at a
// time, and one file to read. Reading only: a change goes through the chat.
import type { CodeApi, CodeEntry, CodeFile } from "@wasifyai/client";
import { ChevronRight, Eye, File, FileText, Folder, FolderOpen, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { cn } from "../cn";
import { EmptyState } from "../components/empty-state";
import { Spinner } from "../components/spinner";

type Loaded = Record<string, CodeEntry[] | "loading" | "failed">;

const sizeOf = (bytes: number) =>
  bytes < 1000 ? `${bytes} bytes` : `${(bytes / 1000).toFixed(bytes < 100_000 ? 1 : 0)} kB`;

export function Files({
  api,
  sessionId,
  project,
}: { api: CodeApi; sessionId: string; project: string }) {
  const [folders, setFolders] = useState<Loaded>({});
  const [open, setOpen] = useState<Set<string>>(() => new Set([""]));
  const [file, setFile] = useState<CodeFile | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<{ entries: CodeEntry[]; more: boolean } | null>(null);

  // find by name, a moment after the person stops typing
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setFound(null);
      return;
    }
    let gone = false;
    const timer = setTimeout(() => {
      api
        .find(sessionId, q)
        .then((out) => {
          if (!gone) setFound(out);
        })
        .catch(() => {
          if (!gone) setFound({ entries: [], more: false });
        });
    }, 200);
    return () => {
      gone = true;
      clearTimeout(timer);
    };
  }, [api, sessionId, query]);

  const load = useCallback(
    async (path: string) => {
      setFolders((f) => ({ ...f, [path]: "loading" }));
      try {
        const entries = await api.files(sessionId, path);
        setFolders((f) => ({ ...f, [path]: entries }));
      } catch {
        setFolders((f) => ({ ...f, [path]: "failed" }));
      }
    },
    [api, sessionId],
  );

  useEffect(() => {
    setFolders({});
    setOpen(new Set([""]));
    setFile(null);
    setChosen(null);
    void load("");
  }, [load]);

  const toggle = (path: string) => {
    setOpen((was) => {
      const next = new Set(was);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    if (folders[path] === undefined || folders[path] === "failed") void load(path);
  };

  const read = async (path: string) => {
    setChosen(path);
    setProblem(null);
    try {
      setFile(await api.file(sessionId, path));
    } catch {
      setFile(null);
      setProblem("That file could not be read.");
    }
  };

  const rows = (path: string, depth: number) => {
    const entries = folders[path];
    if (entries === "loading" || entries === undefined) {
      return (
        <li className="px-2 py-1" style={{ paddingInlineStart: `${depth * 14 + 8}px` }}>
          <Spinner className="size-3.5" />
        </li>
      );
    }
    if (entries === "failed") {
      return (
        <li
          className="px-2 py-1 text-xs text-destructive"
          style={{ paddingInlineStart: `${depth * 14 + 8}px` }}
        >
          This folder could not be read.
        </li>
      );
    }
    if (entries.length === 0) {
      return (
        <li
          className="px-2 py-1 text-xs text-muted-foreground"
          style={{ paddingInlineStart: `${depth * 14 + 8}px` }}
        >
          Empty
        </li>
      );
    }
    return entries.map((entry) => {
      const isOpen = open.has(entry.path);
      const Icon = entry.kind === "folder" ? (isOpen ? FolderOpen : Folder) : File;
      return (
        <li key={entry.path}>
          <button
            type="button"
            aria-expanded={entry.kind === "folder" ? isOpen : undefined}
            aria-current={chosen === entry.path ? "true" : undefined}
            onClick={() => (entry.kind === "folder" ? toggle(entry.path) : void read(entry.path))}
            style={{ paddingInlineStart: `${depth * 14 + 8}px` }}
            className="flex w-full items-center gap-1.5 rounded-md py-1 pe-2 text-start text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-[current=true]:bg-accent aria-[current=true]:font-medium"
          >
            {entry.kind === "folder" ? (
              <ChevronRight
                aria-hidden="true"
                className={cn("size-3 shrink-0 transition-transform", isOpen && "rotate-90")}
              />
            ) : (
              <span className="w-3 shrink-0" />
            )}
            <Icon aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate">{entry.name}</span>
          </button>
          {entry.kind === "folder" && isOpen ? (
            <ul className="m-0 list-none p-0">{rows(entry.path, depth + 1)}</ul>
          ) : null}
        </li>
      );
    });
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(9rem,15rem)_minmax(0,1fr)]">
      <div className="flex min-h-0 flex-col border-e">
        <label className="flex items-center gap-1.5 border-b px-2 py-1.5 text-muted-foreground">
          <Search aria-hidden="true" className="size-3.5 shrink-0" />
          <input
            type="search"
            aria-label="Find a file by name"
            placeholder="Find a file by name"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full min-w-0 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
        </label>
        {found ? (
          <nav aria-label="Files found" className="min-h-0 flex-1 overflow-auto p-1.5">
            {found.entries.length === 0 ? (
              <p className="m-0 px-2 py-1 text-xs text-muted-foreground">
                No file has that in its name.
              </p>
            ) : (
              <ul className="m-0 list-none p-0">
                {found.entries.map((entry) => (
                  <li key={entry.path}>
                    <button
                      type="button"
                      aria-current={chosen === entry.path ? "true" : undefined}
                      onClick={() => void read(entry.path)}
                      title={entry.path}
                      className="grid w-full rounded-md px-2 py-1 text-start text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-[current=true]:bg-accent"
                    >
                      <span className="truncate">{entry.name}</span>
                      <span className="truncate text-xs text-muted-foreground">{entry.path}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {found.more ? (
              <p className="m-0 px-2 py-1 text-xs text-muted-foreground">
                There are more. Type more of the name.
              </p>
            ) : null}
          </nav>
        ) : (
          <nav aria-label={`Files in ${project}`} className="min-h-0 flex-1 overflow-auto p-1.5">
            <ul className="m-0 list-none p-0">{rows("", 0)}</ul>
          </nav>
        )}
      </div>
      <div className="flex min-h-0 min-w-0 flex-col">
        {file && !problem ? (
          <>
            <div className="flex items-center gap-2 border-b px-3 py-1.5">
              <code className="truncate text-xs">{file.path}</code>
            </div>
            {file.binary ? (
              <EmptyState
                size="sm"
                icon={File}
                title="This file is not text"
                text={`It is ${sizeOf(file.bytes)}. Open it with your own programs.`}
                className="m-auto"
              />
            ) : (
              <pre
                // biome-ignore lint/a11y/noNoninteractiveTabindex: a long file is scrolled with the keyboard
                tabIndex={0}
                aria-label={`The file ${file.path}`}
                className="m-0 min-h-0 flex-1 overflow-auto p-0 text-xs leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <code className="grid grid-cols-[auto_minmax(0,1fr)]">
                  {file.text
                    .replace(/\n$/, "")
                    .split("\n")
                    .map((line, n) => (
                      // biome-ignore lint/suspicious/noArrayIndexKey: lines of a file are in order and never move
                      <span key={n} className="contents">
                        <span
                          aria-hidden="true"
                          className="select-none border-e px-2 text-end text-muted-foreground"
                        >
                          {n + 1}
                        </span>
                        <span className="px-3 whitespace-pre">{line || " "}</span>
                      </span>
                    ))}
                </code>
              </pre>
            )}
            <p className="m-0 flex items-center gap-1.5 border-t px-3 py-1.5 text-xs text-muted-foreground">
              <Eye aria-hidden="true" className="size-3" />
              {file.binary
                ? "Read only."
                : `Read only. ${file.lines} line${file.lines === 1 ? "" : "s"}.${
                    file.cut ? " Only the beginning of this long file is shown." : ""
                  }`}
            </p>
          </>
        ) : (
          <EmptyState
            size="sm"
            icon={FileText}
            title={problem ?? "Choose a file to read it"}
            text="Files open here to read. To change one, use your own editor."
            className="m-auto px-4"
          />
        )}
      </div>
    </div>
  );
}
