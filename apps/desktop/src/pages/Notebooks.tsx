// SPDX-License-Identifier: AGPL-3.0-only
// View Notebooks: the notebooks of this computer as cards.
import type { NotebookSummary } from "@wasifyai/client";
import { NotebookList, SetupCard } from "@wasifyai/ui";
import { useCallback, useEffect, useState } from "react";
import { notebooksApi } from "../api";
import { useNotebookSetup } from "../notebook-setup";
import { newNotebook, openNotebook } from "../router";

export function NotebooksPage() {
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const setup = useNotebookSetup();

  const load = useCallback(async () => {
    try {
      setNotebooks(await notebooksApi.list());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The notebooks could not be listed.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const items = setup.items;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-2 pb-10">
      <NotebookList
        notebooks={notebooks}
        loading={loading}
        error={error}
        onOpen={(n) => openNotebook(n.id)}
        onCreate={newNotebook}
        onRename={async (n) => {
          const next = window.prompt("Name this notebook", n.title)?.trim();
          if (!next || next === n.title) return;
          try {
            await notebooksApi.rename(n.id, next);
            await load();
          } catch (e) {
            setError(e instanceof Error ? e.message : "The name could not be changed.");
          }
        }}
        onRemove={async (n) => {
          const what = n.sources ? ` and its ${n.sources} source${n.sources === 1 ? "" : "s"}` : "";
          if (!window.confirm(`Delete “${n.title}”${what}? This cannot be undone.`)) return;
          try {
            await notebooksApi.remove(n.id);
            await load();
          } catch (e) {
            setError(e instanceof Error ? e.message : "The notebook could not be deleted.");
          }
        }}
        onFind={(q) => notebooksApi.find(q)}
      />
      {items.some((i) => i.state !== "ready") ? (
        <div className="px-8">
          <SetupCard items={items} onStart={(id) => void setup.start(id)} />
        </div>
      ) : null}
    </div>
  );
}
