"use client";

import { type HubStyleFiles, type Style, StyleError, type StylesApi } from "@wasifyai/client";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { Button } from "../../components/button";
import { Modal } from "../../components/dialog";
import { Bar } from "../../components/progress-bar";
import { Spinner } from "../../components/spinner";
import { formatBytes } from "../../notebook/format";

const FIELD =
  "h-10 w-full rounded-md border bg-transparent px-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring";

type Phase =
  | { kind: "ask" }
  | { kind: "looking" }
  | { kind: "consent" }
  | { kind: "files"; found: HubStyleFiles }
  | { kind: "getting"; found: HubStyleFiles; file: string; done: number; total: number }
  | { kind: "added"; style: Style };

/**
 * "Get a style from Hugging Face" (ADR-0091 decision 3, ADR-0064): a name or address; nothing is asked of
 * huggingface.co before the person allowed browsing; only .safetensors files are offered, each with its size;
 * the file is fetched only after "Download … and add", and checked when it arrives before it is kept.
 */
export function HubStyleDialog({
  api,
  onClose,
  onAdded,
  pollMs = 1000,
  initialRepo,
  pinned,
}: {
  api: StylesApi;
  onClose: () => void;
  onAdded: (style: Style) => void;
  pollMs?: number;
  /** "Get it again": the repository a missing style came from, looked at once the dialog opens */
  initialRepo?: string;
  /** a recommended style: the file to choose, and the checksum it must have */
  pinned?: { file: string; sha256: string };
}) {
  const id = useId();
  const [repo, setRepo] = useState(initialRepo ?? "");
  const [phase, setPhase] = useState<Phase>({ kind: "ask" });
  const [file, setFile] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const gone = useRef(false);
  useEffect(() => {
    gone.current = false; // set again on every mount: React's checks mount a component twice
    return () => {
      gone.current = true;
    };
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: once, for the repository it was opened with
  useEffect(() => {
    if (initialRepo) void look(undefined, initialRepo);
  }, []);

  async function look(e?: FormEvent, name: string = repo) {
    e?.preventDefault();
    if (!name.trim()) return;
    setProblem(null);
    setPhase({ kind: "looking" });
    try {
      const found = await api.hubFiles(name.trim());
      setFile(
        pinned && found.files.some((f) => f.name === pinned.file)
          ? pinned.file
          : found.files.length === 1
            ? (found.files[0]?.name ?? null)
            : null,
      );
      setPhase({ kind: "files", found });
    } catch (err) {
      if (err instanceof StyleError && err.code === "consent_needed") {
        setPhase({ kind: "consent" });
        return;
      }
      setProblem(err instanceof Error ? err.message : "Hugging Face could not be asked.");
      setPhase({ kind: "ask" });
    }
  }

  async function allow() {
    try {
      await api.allowHub();
      await look();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "That could not be changed.");
    }
  }

  async function get(found: HubStyleFiles) {
    const chosen = found.files.find((f) => f.name === file);
    if (!chosen) return;
    setProblem(null);
    try {
      const d = await api.hubDownload(
        found.repo,
        chosen.name,
        chosen.size,
        pinned?.file === chosen.name ? pinned.sha256 : undefined,
      );
      setPhase({ kind: "getting", found, file: chosen.name, done: 0, total: chosen.size });
      for (;;) {
        await new Promise((r) => setTimeout(r, pollMs));
        if (gone.current) return;
        const job = await api.hubJob(d.id);
        const dl = job.download;
        if (dl.status === "failed" || dl.status === "cancelled") {
          throw new Error(dl.error || "The download stopped.");
        }
        if (job.refused) throw new Error(job.refused);
        if (job.style) {
          setPhase({ kind: "added", style: job.style });
          return;
        }
        setPhase({
          kind: "getting",
          found,
          file: chosen.name,
          done: dl.bytes_done,
          total: dl.bytes_total,
        });
      }
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "The style could not be fetched.");
      setPhase({ kind: "files", found });
    }
  }

  const found = phase.kind === "files" || phase.kind === "getting" ? phase.found : null;
  const chosen = found?.files.find((f) => f.name === file) ?? null;

  return (
    <Modal label="Get a style from Hugging Face" onClose={onClose} wide>
      <p className="m-0 text-muted-foreground text-sm">
        This contacts huggingface.co to read the list of a repository's files. Nothing else is sent.
        A file is fetched only when you choose it.
      </p>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => void look(e)}>
        <label htmlFor={`${id}-repo`} className="grid min-w-0 flex-1 gap-1.5 text-sm">
          <span className="text-muted-foreground">Name or address</span>
          <input
            id={`${id}-repo`}
            className={FIELD}
            placeholder="owner/name"
            value={repo}
            maxLength={300}
            spellCheck={false}
            onChange={(e) => setRepo(e.target.value)}
            disabled={phase.kind === "getting"}
          />
        </label>
        <Button
          type="submit"
          variant="outline"
          disabled={!repo.trim() || phase.kind === "looking" || phase.kind === "getting"}
        >
          {phase.kind === "looking" ? <Spinner /> : null}
          Look
        </Button>
      </form>

      {phase.kind === "consent" ? (
        <div className="grid gap-2 rounded-md border p-3 text-sm">
          <p className="m-0">
            Browsing Hugging Face is off. Turn it on to read this repository's files.
          </p>
          <div>
            <Button type="button" onClick={() => void allow()}>
              Allow browsing Hugging Face
            </Button>
          </div>
        </div>
      ) : null}

      {found ? (
        <div className="grid gap-2">
          {found.stale ? (
            <p className="m-0 text-warn text-sm">
              Hugging Face could not be reached: this list is from before.
            </p>
          ) : null}
          {found.files.length === 0 ? (
            <p className="m-0 text-sm">This repository has no .safetensors file to offer.</p>
          ) : (
            <fieldset className="m-0 grid gap-1 border-0 p-0">
              <legend className="mb-1 text-muted-foreground text-sm">Files in {found.repo}</legend>
              {found.files.map((f) => (
                <label key={f.name} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name={`${id}-file`}
                    checked={file === f.name}
                    onChange={() => setFile(f.name)}
                    disabled={phase.kind === "getting"}
                  />
                  <span className="min-w-0 flex-1 truncate font-mono">{f.name}</span>
                  <span className="text-muted-foreground">{formatBytes(f.size)}</span>
                </label>
              ))}
            </fieldset>
          )}
          {found.refused.map((r) => (
            <p key={r.name} className="m-0 text-muted-foreground text-sm">
              <span className="font-mono">{r.name}</span>: {r.why}
            </p>
          ))}
          <p className="m-0 text-sm">
            {found.made_for_base === true
              ? "The repository says it was made for klein base: the look may not show on this model."
              : found.made_for_base === false
                ? "The repository says it was made for FLUX.2 klein. Checked again when it arrives."
                : "What it was made for is checked when it arrives."}
            {found.trigger ? ` Its word: ${found.trigger}.` : ""}
            {found.gated ? " It needs a Hugging Face account that accepted its terms." : ""}
          </p>
        </div>
      ) : null}

      {phase.kind === "getting" ? (
        <div className="grid gap-1.5">
          <Bar value={phase.total > 0 ? phase.done / phase.total : 0} />
          <output className="text-muted-foreground text-sm">
            Getting {phase.file}: {formatBytes(phase.done)} of {formatBytes(phase.total)}. It is
            checked when it arrives.
          </output>
        </div>
      ) : null}

      {phase.kind === "added" ? (
        <output className="text-sm">{phase.style.title} was checked and added.</output>
      ) : null}

      {problem ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {problem}
        </p>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2">
        {phase.kind === "added" ? (
          <Button type="button" onClick={() => onAdded(phase.style)}>
            Use it in this picture
          </Button>
        ) : (
          <>
            <Button type="button" variant="outline" onClick={onClose}>
              {phase.kind === "getting" ? "Close (it keeps going)" : "Not now"}
            </Button>
            <Button
              type="button"
              disabled={!found || !chosen || phase.kind === "getting"}
              onClick={() => found && void get(found)}
            >
              {chosen ? `Download ${formatBytes(chosen.size)} and add` : "Download and add"}
            </Button>
          </>
        )}
      </div>
    </Modal>
  );
}
