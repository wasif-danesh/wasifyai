"use client";

import { FileText, Globe, Upload } from "lucide-react";
import { type DragEvent, useId, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Textarea } from "../components/textarea";

/** What the engine reads (its hardening list): shown to the person and given to the file picker. */
export const SOURCE_TYPES = [
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".html",
  ".htm",
  ".csv",
  ".md",
  ".markdown",
  ".txt",
  ".text",
  ".png",
  ".jpg",
  ".jpeg",
  ".tif",
  ".tiff",
  ".bmp",
  ".webp",
] as const;

export const SOURCE_ACCEPT = SOURCE_TYPES.join(",");
const MAX_BYTES = 100 * 1024 * 1024;

/** A problem with a file that can be known before it is sent, or null. */
export function fileProblem(file: { name: string; size: number }): string | null {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!(SOURCE_TYPES as readonly string[]).includes(ext)) {
    return `${file.name}: this kind of file cannot be added.`;
  }
  if (file.size > MAX_BYTES) return `${file.name}: larger than 100 MB.`;
  if (file.size === 0) return `${file.name}: the file is empty.`;
  return null;
}

export type AddSourcesProps = {
  onFiles: (files: File[]) => void;
  onNote: (title: string, content: string) => void;
  busy?: boolean;
  /** Shown above: why this is open (a new notebook, or more sources). */
  heading?: string;
  /** Closes it, when it is a dialog. */
  onClose?: () => void;
  className?: string;
};

/**
 * Where sources come in: files (picked or dropped) and copied text. Websites and Drive are shown as
 * not yet, as in the plan; nothing here reaches the network.
 */
export function AddSources({
  onFiles,
  onNote,
  busy,
  heading = "Add sources",
  onClose,
  className,
}: AddSourcesProps) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [text, setText] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const titleId = useId();
  const bodyId = useId();

  function take(list: FileList | File[]) {
    const files = Array.from(list);
    const bad = files.map(fileProblem).filter((p): p is string => p !== null);
    const ok = files.filter((f) => fileProblem(f) === null);
    setProblem(bad.length ? bad.join(" ") : null);
    if (ok.length) onFiles(ok);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    if (e.dataTransfer?.files?.length) take(e.dataTransfer.files);
  }

  return (
    <section
      aria-label="Add sources"
      className={cn("grid gap-5 rounded-3xl border bg-card p-6 shadow-card", className)}
    >
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-medium text-xl">{heading}</h2>
          <p className="mt-1 text-muted-foreground text-sm">
            Documents stay on this computer. Ask questions about them once they are read.
          </p>
        </div>
        {onClose ? (
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        ) : null}
      </header>

      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={busy} onClick={() => input.current?.click()}>
          <Upload /> Upload files
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={() => setText((v) => !v)}>
          <FileText /> Copied text
        </Button>
        <Button type="button" variant="outline" disabled title="Not yet">
          <Globe /> Websites <span className="text-muted-foreground text-xs">Soon</span>
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={SOURCE_ACCEPT}
          aria-label="Choose files"
          onChange={(e) => {
            if (e.target.files) take(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {text ? (
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!body.trim()) return;
            onNote(title.trim() || "Pasted text", body);
            setBody("");
            setTitle("");
            setText(false);
          }}
        >
          <label htmlFor={titleId} className="font-medium text-sm">
            Name
          </label>
          <input
            id={titleId}
            value={title}
            maxLength={200}
            placeholder="Pasted text"
            onChange={(e) => setTitle(e.target.value)}
            className="h-10 rounded-md border bg-background px-3"
          />
          <label htmlFor={bodyId} className="font-medium text-sm">
            Text
          </label>
          <Textarea
            id={bodyId}
            rows={6}
            value={body}
            placeholder="Paste or type the text"
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="flex gap-2">
            <Button type="submit" disabled={!body.trim() || busy}>
              Add text
            </Button>
            <Button type="button" variant="ghost" onClick={() => setText(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}

      {/* biome-ignore lint/a11y/useSemanticElements: a drop target is not a form control */}
      <div
        role="group"
        aria-label="Drop files here"
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cn(
          "grid place-items-center rounded-2xl border-2 border-dashed px-6 py-10 text-center text-muted-foreground",
          over && "border-primary bg-primary/5 text-foreground",
        )}
      >
        <Upload className="mb-2 size-6" aria-hidden="true" />
        <p>Drag and drop your files here.</p>
        <p className="mt-1 text-xs">
          PDF, Word, PowerPoint, Excel, text, Markdown, HTML, CSV, pictures
        </p>
      </div>

      {problem ? (
        <output className="text-destructive text-sm" role="alert">
          {problem}
        </output>
      ) : null}
    </section>
  );
}
