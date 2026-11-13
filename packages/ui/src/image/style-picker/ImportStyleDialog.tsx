"use client";

import type { Style, StylesApi } from "@wasifyai/client";
import { useId, useRef, useState } from "react";
import { Button } from "../../components/button";
import { Modal } from "../../components/dialog";
import { Spinner } from "../../components/spinner";
import { fitLine } from "./fit";

const FIELD =
  "h-10 rounded-md border bg-transparent px-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * "Add a style from this computer" (ADR-0091 decisions 3 and 5): the person chooses a .safetensors file; the
 * engine reads its header, checks it and keeps a copy (the original is not changed or moved); the dialog says
 * what it is and lets the person name it and set its word. Cancel takes a copy made here away again.
 */
export function ImportStyleDialog({
  api,
  onClose,
  onAdded,
}: {
  api: StylesApi;
  onClose: () => void;
  onAdded: (style: Style) => void;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const opened = useRef(Date.now() / 1000);
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [style, setStyle] = useState<Style | null>(null);
  const [title, setTitle] = useState("");
  const [word, setWord] = useState("");
  const [fileName, setFileName] = useState("");

  async function choose(file: File | undefined) {
    if (!file) return;
    setProblem(null);
    setStyle(null);
    if (!file.name.toLowerCase().endsWith(".safetensors")) {
      setProblem(
        "Choose a .safetensors file. .ckpt and .pt files are not used: they can run code.",
      );
      return;
    }
    setChecking(true);
    setFileName(file.name);
    try {
      const s = await api.importFile(file, file.name);
      setStyle(s);
      setTitle(s.title);
      setWord(s.trigger ?? "");
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That file could not be added.");
    } finally {
      setChecking(false);
    }
  }

  /** a copy made while this dialog was open goes again; one that was already here stays */
  async function cancel() {
    if (style && style.added_at >= opened.current - 1) await api.remove(style.id).catch(() => {});
    onClose();
  }

  async function add() {
    if (!style) return;
    const change: { title?: string; trigger?: string } = {};
    if (title.trim() && title.trim() !== style.title) change.title = title.trim();
    if (word.trim() !== (style.trigger ?? "")) change.trigger = word.trim();
    try {
      onAdded(Object.keys(change).length ? await api.update(style.id, change) : style);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The style could not be saved.");
    }
  }

  return (
    <Modal label="Add a style from this computer" onClose={() => void cancel()}>
      <div className="grid gap-2">
        <input
          ref={input}
          id={`${id}-file`}
          type="file"
          accept=".safetensors"
          className="sr-only"
          onChange={(e) => void choose(e.target.files?.[0])}
        />
        <Button
          type="button"
          variant="outline"
          onClick={() => input.current?.click()}
          disabled={checking}
        >
          {checking ? <Spinner /> : null}
          {checking ? "Checking…" : style ? "Choose another file" : "Choose a .safetensors file"}
        </Button>
        <p className="m-0 text-muted-foreground text-xs">
          Not .ckpt or .pt files: those can run code. A copy is kept in the app's own folder; your
          file is not changed or moved.
        </p>
      </div>

      {problem ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {problem}
        </p>
      ) : null}

      {style ? (
        <div className="grid gap-3">
          <p className={`m-0 text-sm ${style.fit === "fits" ? "" : "text-warn"}`}>
            Checked: {fitLine(style)}
            {style.rank ? ` · rank ${style.rank}` : ""}.{" "}
            <span className="text-muted-foreground">{fileName}</span>
          </p>
          <label htmlFor={`${id}-title`} className="grid gap-1.5 text-sm">
            <span className="text-muted-foreground">Name</span>
            <input
              id={`${id}-title`}
              className={FIELD}
              value={title}
              maxLength={80}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label htmlFor={`${id}-word`} className="grid gap-1.5 text-sm">
            <span className="text-muted-foreground">
              Word{" "}
              {style.trigger ? "(found in the file)" : "(optional: the word its maker says to use)"}
            </span>
            <input
              id={`${id}-word`}
              className={FIELD}
              value={word}
              maxLength={80}
              onChange={(e) => setWord(e.target.value)}
            />
          </label>
        </div>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" onClick={() => void cancel()}>
          Cancel
        </Button>
        <Button type="button" onClick={() => void add()} disabled={!style || !style.selectable}>
          Add this style
        </Button>
      </div>
    </Modal>
  );
}
