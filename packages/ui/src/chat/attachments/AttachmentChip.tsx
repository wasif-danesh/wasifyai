"use client";
// What is attached to a message, in the box before it is sent and under the person's message after (ADR-0083, CO2). A picture is a
// thumbnail; a document is a chip with its name and how much of it there is. Plain text only: the name came from a file.
import type { AttachmentInfo } from "@wasifyai/client";
import { FileText, X } from "lucide-react";
import { Spinner } from "../../components/spinner";

export type ChipState = "uploading" | "ready" | "failed";

/** One thing attached: what to show, how far it got, and what went wrong in words. */
export type ChipData = AttachmentInfo & {
  state?: ChipState;
  /** a short line under the name: "12 pages", "Only the start is used" */
  detail?: string;
  error?: string;
};

export function detailOf(file: {
  kind: string;
  pages?: number;
  chars?: number;
  truncated?: boolean;
}): string {
  if (file.kind !== "document") return "";
  if (file.truncated) return "Only the start is used";
  if (file.pages) return file.pages === 1 ? "1 page" : `${file.pages} pages`;
  if (file.chars) return `${file.chars.toLocaleString()} characters`;
  return "";
}

export function AttachmentChip({
  file,
  onRemove,
}: {
  file: ChipData;
  /** the box can take it back; a sent message cannot */
  onRemove?: () => void;
}) {
  const failed = file.state === "failed";
  const working = file.state === "uploading";
  const remove = onRemove ? (
    <button
      type="button"
      aria-label={`Remove ${file.name}`}
      onClick={onRemove}
      className="absolute -end-1.5 -top-1.5 grid size-5 place-items-center rounded-full border bg-card text-muted-foreground hover:bg-accent"
    >
      <X className="size-3" aria-hidden="true" />
    </button>
  ) : null;
  if (file.kind === "image" && !failed) {
    return (
      <li className="relative list-none">
        {file.url ? (
          <img
            src={file.url}
            alt={file.name}
            className={`size-14 rounded-lg border object-cover ${working ? "opacity-50" : ""}`}
          />
        ) : (
          <span
            role="img"
            aria-label={file.name}
            className="grid size-14 place-items-center rounded-lg border bg-muted text-muted-foreground text-xs"
          >
            {file.name.slice(0, 3)}
          </span>
        )}
        {working ? (
          <span className="absolute inset-0 grid place-items-center">
            <Spinner />
          </span>
        ) : null}
        {remove}
      </li>
    );
  }
  return (
    <li
      className={`relative flex max-w-60 list-none items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
        failed ? "border-destructive" : ""
      }`}
    >
      {working ? <Spinner /> : <FileText className="size-4 shrink-0" aria-hidden="true" />}
      <span className="min-w-0">
        <span dir="auto" className="block truncate">
          {file.name}
        </span>
        <span
          className={`block truncate text-xs ${failed ? "text-destructive" : "text-muted-foreground"}`}
        >
          {failed ? file.error : working ? "Reading" : file.detail}
        </span>
      </span>
      {remove}
    </li>
  );
}

/** The attachments of a sent message. */
export function MessageAttachments({ files }: { files: AttachmentInfo[] }) {
  if (!files.length) return null;
  return (
    <ul aria-label="Attached files" className="m-0 flex list-none flex-wrap justify-end gap-2 p-0">
      {files.map((f) => (
        <AttachmentChip key={f.id} file={{ ...f, detail: detailOf(f), state: "ready" }} />
      ))}
    </ul>
  );
}
