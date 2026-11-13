"use client";

import { Notice } from "@/components/Notice";
import { adminStyles } from "@/lib/library";
import type { Style } from "@wasifyai/client";
import { Button, ConfirmDialog, HubStyleDialog, fitLine } from "@wasifyai/ui";
import { useCallback, useEffect, useState } from "react";

/** Admin > Styles (ADR-0091 S5): the service's styles, adding one from Hugging Face, deleting one. */
export function StylesAdmin() {
  const [styles, setStyles] = useState<Style[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<Style | null>(null);

  const reload = useCallback(async () => {
    try {
      setStyles((await adminStyles.list()).styles);
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The styles could not be read.");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function remove(s: Style) {
    setDeleting(null);
    try {
      await adminStyles.remove(s.id);
      await reload();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That style could not be deleted.");
    }
  }

  return (
    <section className="grid gap-3" aria-label="The service's styles">
      <div>
        <Button type="button" onClick={() => setAdding(true)}>
          Add a style from Hugging Face
        </Button>
      </div>
      {problem ? (
        <Notice tone="error" title="Something went wrong">
          {problem}
        </Notice>
      ) : null}
      {styles === null ? null : styles.length === 0 ? (
        <p className="m-0 text-muted-foreground">
          No styles yet. People see none on the image screens.
        </p>
      ) : (
        <ul className="m-0 grid list-none gap-2 p-0">
          {styles.map((s) => (
            <li key={s.id} className="flex flex-wrap items-start gap-3 rounded-md border px-3 py-2">
              <div className="grid min-w-0 flex-1 gap-0.5">
                <span className="font-medium">{s.title}</span>
                <span className="text-muted-foreground text-sm">{fitLine(s)}</span>
                <span className="text-muted-foreground text-sm">
                  {s.source.repo ? `From ${s.source.repo}` : ""}
                  {s.trigger ? ` · word: ${s.trigger}` : ""}
                </span>
              </div>
              <Button type="button" size="sm" variant="outline" onClick={() => setDeleting(s)}>
                Delete
              </Button>
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <HubStyleDialog
          api={adminStyles}
          onClose={() => {
            setAdding(false);
            void reload();
          }}
          onAdded={() => {
            setAdding(false);
            void reload();
          }}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title={`Delete ${deleting.title}?`}
          message="It goes from the service. People cannot choose it any more; pictures made with it stay."
          onConfirm={() => void remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      ) : null}
    </section>
  );
}
