"use client";

import { webImages, webNotebooks } from "@/lib/library";
import { NEW_NOTEBOOK } from "@/lib/notebook-ids";
import { webClient } from "@/lib/run-client";
import type { NotebookSummary } from "@wasifyai/client";
import { Button, NotebookList, NotebookPlaceProvider, NotebookWorkspace } from "@wasifyai/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

const DRAFT_TITLE = "Untitled notebook";

/** View Notebooks: the person's notebooks as cards (the shared screen, also the desktop's). */
export function NotebookListScreen() {
  const router = useRouter();
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setNotebooks(await webNotebooks.list());
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

  return (
    <NotebookPlaceProvider place="hosted">
      <NotebookList
        className="px-0 py-0"
        notebooks={notebooks}
        loading={loading}
        error={error}
        onOpen={(n) => router.push(`/notebooks/${n.id}`)}
        onCreate={() => router.push(`/notebooks/${NEW_NOTEBOOK}`)}
        onRename={async (n) => {
          const next = window.prompt("Name this notebook", n.title)?.trim();
          if (!next || next === n.title) return;
          try {
            await webNotebooks.rename(n.id, next);
            await load();
          } catch (e) {
            setError(e instanceof Error ? e.message : "The name could not be changed.");
          }
        }}
        onRemove={async (n) => {
          const what = n.sources ? ` and its ${n.sources} source${n.sources === 1 ? "" : "s"}` : "";
          if (!window.confirm(`Delete “${n.title}”${what}? This cannot be undone.`)) return;
          try {
            await webNotebooks.remove(n.id);
            await load();
          } catch (e) {
            setError(e instanceof Error ? e.message : "The notebook could not be deleted.");
          }
        }}
        onFind={(q) => webNotebooks.find(q)}
      />
    </NotebookPlaceProvider>
  );
}

/** One notebook, or a new one (`/notebooks/new`): a draft that is saved when its first source is added
 * and then has its own address, without the page being reloaded. */
export function NotebookScreen({ notebook }: { notebook: string }) {
  const router = useRouter();
  const [savedId, setSavedId] = useState<string | null>(
    notebook === NEW_NOTEBOOK ? null : notebook,
  );
  const [title, setTitle] = useState(DRAFT_TITLE);
  const [missing, setMissing] = useState(false);
  const saving = useRef<Promise<string> | null>(null);
  const titleRef = useRef(title);
  titleRef.current = title;

  // an existing notebook: read it (which also marks it opened)
  useEffect(() => {
    if (!savedId) return;
    let gone = false;
    webNotebooks
      .get(savedId)
      .then((n) => !gone && setTitle(n.title))
      .catch(() => !gone && setMissing(true));
    return () => {
      gone = true;
    };
  }, [savedId]);

  const ensureNotebook = useCallback((): Promise<string> => {
    if (savedId) return Promise.resolve(savedId);
    if (!saving.current) {
      saving.current = webNotebooks
        .create(titleRef.current.trim() || DRAFT_TITLE)
        .then((n) => {
          setSavedId(n.id);
          window.history.replaceState(null, "", `/notebooks/${n.id}`);
          return n.id;
        })
        .finally(() => {
          saving.current = null;
        });
    }
    return saving.current;
  }, [savedId]);

  async function rename(next: string) {
    setTitle(next);
    if (!savedId) {
      await ensureNotebook(); // a name is a reason to keep the draft
      return;
    }
    try {
      setTitle((await webNotebooks.rename(savedId, next)).title);
    } catch {
      // the old name stays
    }
  }

  if (missing) {
    return (
      <div className="mx-auto grid max-w-md gap-4 py-20 text-center">
        <h1 className="font-medium text-2xl">That notebook is not here</h1>
        <p className="text-muted-foreground">It may have been deleted.</p>
        <div>
          <Button asChild>
            <Link href="/notebooks">Back to notebooks</Link>
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div data-workspace className="h-[calc(100dvh-3.5rem)] min-h-[32rem] min-w-0">
      <NotebookPlaceProvider place="hosted">
        <NotebookWorkspace
          api={webNotebooks}
          runs={webClient}
          notebookId={savedId}
          title={title}
          onTitle={(t) => void rename(t)}
          ensureNotebook={ensureNotebook}
          searchReady
          chatModelChosen
          imageUrl={async (id) => (await webImages.get(id)).image_url}
          onBack={() => router.push("/notebooks")}
        />
      </NotebookPlaceProvider>
    </div>
  );
}
