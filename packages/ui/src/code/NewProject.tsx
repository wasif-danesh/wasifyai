"use client";
// "Start in a new, empty folder" (mockup `start`): a new project from a starter. The person names it and
// chooses the folder it is made in; the app writes the starter's files there and opens a session on it.
import type { CodeApi, CodeSession, CodeStarter } from "@wasifyai/client";
import { FolderOpen } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Button } from "../components/button";
import { Modal } from "../components/dialog";
import { Input } from "../components/input";
import { Spinner } from "../components/spinner";

export function NewProject({
  api,
  pickFolder,
  model,
  onClose,
  onMade,
}: {
  api: CodeApi;
  pickFolder: () => Promise<string | null>;
  model: string | undefined;
  onClose: () => void;
  onMade: (session: CodeSession) => void;
}) {
  const [starters, setStarters] = useState<CodeStarter[] | null>(null);
  const [starter, setStarter] = useState("");
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const nameId = useId();
  useEffect(() => {
    let gone = false;
    api
      .starters()
      .then((found) => {
        if (gone) return;
        setStarters(found);
        setStarter(found[0]?.id ?? "");
      })
      .catch(() => {
        if (!gone) setProblem("The starters could not be read.");
      });
    return () => {
      gone = true;
    };
  }, [api]);
  const choose = async () => {
    const folder = await pickFolder();
    if (folder) setParent(folder);
  };
  const make = async () => {
    setBusy(true);
    setProblem(null);
    try {
      onMade(await api.newProject({ parent, name: name.trim(), starter, model }));
    } catch (e) {
      setProblem(e instanceof Error && e.message ? e.message : "The project could not be made.");
      setBusy(false);
    }
  };
  const chosen = starters?.find((s) => s.id === starter);
  return (
    <Modal label="Start in a new, empty folder" onClose={onClose}>
      {starters ? (
        <>
          <fieldset className="m-0 grid gap-2 border-0 p-0">
            <legend className="mb-1 p-0 text-sm font-medium">What to start from</legend>
            {starters.map((s) => (
              <label
                key={s.id}
                className="flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-sm has-checked:border-primary has-checked:bg-primary/5"
              >
                <input
                  type="radio"
                  name="starter"
                  className="mt-1"
                  checked={starter === s.id}
                  onChange={() => setStarter(s.id)}
                />
                <span className="grid gap-0.5">
                  <span className="font-medium">{s.title}</span>
                  <span className="text-muted-foreground">{s.says}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <div className="grid gap-1.5 text-sm">
            <label htmlFor={nameId} className="font-medium">
              The project’s name
            </label>
            <Input
              id={nameId}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="bakery-site"
              maxLength={64}
              spellCheck={false}
            />
            <span className="text-xs text-muted-foreground">
              It becomes the name of the new folder.
            </span>
          </div>
          <div className="grid gap-1.5 text-sm">
            <span className="font-medium">Where to make it</span>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => void choose()}>
                <FolderOpen /> {parent ? "Choose another folder" : "Choose a folder"}
              </Button>
              {parent ? (
                <code className="min-w-0 truncate rounded bg-muted px-1.5 py-0.5 text-xs">
                  {parent}
                  {name.trim() ? `/${name.trim()}` : ""}
                </code>
              ) : (
                <span className="text-xs text-muted-foreground">
                  The new folder is made inside the one you choose.
                </span>
              )}
            </div>
          </div>
          {chosen?.needs.length ? (
            <p className="m-0 text-xs text-muted-foreground">
              It needs {chosen.needs.join(" and ")}. If this computer’s own is in your home folder,
              the protected area cannot read it: set up “Node for coding projects” in Settings,
              under Optional parts.
            </p>
          ) : null}
        </>
      ) : problem ? null : (
        <Spinner className="size-4" />
      )}
      {problem ? (
        <p role="alert" className="m-0 text-sm text-destructive">
          {problem}
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button disabled={busy || !starter || !name.trim() || !parent} onClick={() => void make()}>
          {busy ? <Spinner className="size-3.5" /> : null} Make the project
        </Button>
      </div>
    </Modal>
  );
}
