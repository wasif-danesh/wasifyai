// SPDX-License-Identifier: AGPL-3.0-only
// One notebook (or a new one, a draft that is saved when its first source is added): sources, the
// conversation and Studio.
import { Button, NotebookWorkspace, Notice, SetupCard } from "@wasifyai/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { client, notebooksApi } from "../api";
import { images } from "../images";
import { useNotebookSetup } from "../notebook-setup";
import { NEW_NOTEBOOK, openNotebook } from "../router";
import { useChatModel } from "../useChatModel";

const DRAFT_TITLE = "Untitled notebook";

export function NotebookPage({
  notebook,
  onAdopt,
  goModels,
}: {
  /** the id from the address, or `new` */
  notebook: string;
  onAdopt: (id: string) => void;
  goModels: () => void;
}) {
  const [savedId, setSavedId] = useState<string | null>(
    notebook === NEW_NOTEBOOK ? null : notebook,
  );
  const [title, setTitle] = useState(DRAFT_TITLE);
  const [missing, setMissing] = useState(false);
  const saving = useRef<Promise<string> | null>(null);
  const titleRef = useRef(title);
  titleRef.current = title;
  const model = useChatModel();
  const setup = useNotebookSetup();

  // an existing notebook: read it (which also marks it opened)
  useEffect(() => {
    if (!savedId) return;
    let gone = false;
    notebooksApi
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
      saving.current = notebooksApi
        .create(titleRef.current.trim() || DRAFT_TITLE)
        .then((n) => {
          setSavedId(n.id);
          onAdopt(n.id);
          return n.id;
        })
        .finally(() => {
          saving.current = null;
        });
    }
    return saving.current;
  }, [savedId, onAdopt]);

  async function rename(next: string) {
    setTitle(next);
    if (!savedId) {
      await ensureNotebook(); // a name is a reason to keep the draft
      return;
    }
    try {
      const n = await notebooksApi.rename(savedId, next);
      setTitle(n.title);
    } catch {
      // the old name stays
    }
  }

  if (missing) {
    return (
      <div className="mx-auto grid max-w-md gap-4 px-8 py-20 text-center">
        <h1 className="font-medium text-2xl">That notebook is not here</h1>
        <p className="text-muted-foreground">It may have been deleted.</p>
        <div>
          <Button type="button" onClick={() => openNotebook(null)}>
            Back to notebooks
          </Button>
        </div>
      </div>
    );
  }

  const pending = setup.items.some((i) => i.state !== "ready");
  const notices = (
    <div className="grid gap-3">
      {pending ? <SetupCard items={setup.items} onStart={(id) => void setup.start(id)} /> : null}
      {model.chosen === false ? (
        <Notice
          tone="info"
          title="Choose a chat model"
          actions={
            <Button type="button" onClick={goModels}>
              Open Models
            </Button>
          }
        >
          Answers are written by the chat model on this computer.
        </Notice>
      ) : null}
    </div>
  );

  return (
    <NotebookWorkspace
      api={notebooksApi}
      runs={client}
      notebookId={savedId}
      title={title}
      onTitle={(t) => void rename(t)}
      ensureNotebook={ensureNotebook}
      notices={pending || model.chosen === false ? notices : undefined}
      searchReady={setup.searchReady}
      chatModelChosen={model.chosen}
      chip={
        model.name ? (
          <span className="rounded-full border px-2.5 py-1 text-muted-foreground text-xs">
            {model.name}
          </span>
        ) : undefined
      }
      imageUrl={async (id) => (await images.get(id)).image_url}
      onNeedModel={goModels}
      onBack={() => openNotebook(null)}
    />
  );
}
