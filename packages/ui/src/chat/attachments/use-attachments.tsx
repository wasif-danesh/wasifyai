"use client";
// Attaching files to the next message (ADR-0083, stage CO2): the picker, drag and drop, paste, the upload of each file, and what
// the run is told (`attachments`). The engine checks everything again; this keeps the person informed while it happens.
import type { AttachmentInfo, UploadedAttachment } from "@wasifyai/client";
import { Paperclip } from "lucide-react";
import {
  type ClipboardEvent,
  type DragEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ComposerOption } from "../composer-options";
import { AttachmentChip, type ChipData, detailOf } from "./AttachmentChip";

export const MAX_ATTACHMENTS = 4;
const PICTURE = /^image\/(png|jpeg|webp)$/;
// what the file picker offers: pictures, and the documents the engine reads (PDF and Office need the document reader)
export const ATTACH_ACCEPT =
  "image/png,image/jpeg,image/webp,.txt,.md,.markdown,.csv,.html,.htm,.pdf,.docx,.pptx,.xlsx";

/** What the box needs to attach: the engine's answer about this model, and the two calls. */
export type AttachControl = {
  /** the model reads pictures (null: not known, so a picture is tried) */
  images: boolean | null;
  documents: boolean;
  /** why a picture will not work, in words, when it will not */
  imagesNote: string;
  upload: (file: Blob, name: string) => Promise<UploadedAttachment>;
  discard?: (id: string) => Promise<void>;
};

type Item = ChipData & { key: string };

function problem(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "That file could not be attached.";
}

export function useAttachments(control: AttachControl | undefined) {
  const [items, setItems] = useState<Item[]>([]);
  const seq = useRef(0);
  const previews = useRef(new Set<string>());
  const input = useRef<HTMLInputElement>(null);
  const live = useRef(control);
  live.current = control;

  const patch = useCallback((key: string, change: Partial<Item>) => {
    setItems((all) => all.map((i) => (i.key === key ? { ...i, ...change } : i)));
  }, []);

  const forget = useCallback((i: Item) => {
    if (i.url && previews.current.delete(i.url)) URL.revokeObjectURL(i.url);
  }, []);

  const add = useCallback(
    (files: File[]) => {
      const c = live.current;
      if (!c || !files.length) return;
      setItems((have) => {
        let room = MAX_ATTACHMENTS - have.length;
        const next: Item[] = [...have];
        for (const file of files) {
          const kind = PICTURE.test(file.type) ? "image" : "document";
          const key = `a${++seq.current}`;
          if (room <= 0) {
            next.push({
              key,
              kind,
              id: key,
              name: file.name,
              state: "failed",
              error: `At most ${MAX_ATTACHMENTS} files fit in one message.`,
            });
            continue;
          }
          if (kind === "image" && c.images === false) {
            next.push({
              key,
              kind,
              id: key,
              name: file.name,
              state: "failed",
              error: c.imagesNote || "This model does not read pictures.",
            });
            continue;
          }
          if (kind === "document" && !c.documents) {
            next.push({
              key,
              kind,
              id: key,
              name: file.name,
              state: "failed",
              error: "Files cannot be attached here.",
            });
            continue;
          }
          room -= 1;
          let url: string | undefined;
          if (kind === "image") {
            try {
              url = URL.createObjectURL(file);
              previews.current.add(url);
            } catch {
              url = undefined; // no preview: the name stands in
            }
          }
          next.push({ key, kind, id: key, name: file.name, url, state: "uploading" });
          c.upload(file, file.name).then(
            (done) =>
              patch(key, {
                state: "ready",
                id: done.id,
                detail: detailOf(done),
                name: done.name || file.name,
              }),
            (e) => patch(key, { state: "failed", error: problem(e) }),
          );
        }
        return next;
      });
    },
    [patch],
  );

  const remove = useCallback(
    (key: string) => {
      setItems((all) => {
        const gone = all.find((i) => i.key === key);
        if (gone) {
          forget(gone);
          if (gone.state === "ready" && gone.id) void live.current?.discard?.(gone.id);
        }
        return all.filter((i) => i.key !== key);
      });
    },
    [forget],
  );

  /** After the message was sent: the files belong to it now, not to the box. */
  const clear = useCallback(() => {
    setItems((all) => {
      for (const i of all) forget(i);
      return [];
    });
  }, [forget]);

  useEffect(
    () => () => {
      for (const u of previews.current) URL.revokeObjectURL(u);
      previews.current.clear();
    },
    [],
  );

  const busy = items.some((i) => i.state === "uploading");
  const ready = useMemo(() => items.filter((i) => i.state === "ready"), [items]);

  const option = useMemo<ComposerOption | null>(
    () =>
      control
        ? {
            id: "attach",
            label: "Attach",
            Icon: Paperclip,
            hint:
              control.images === false
                ? "Attach a document: text, Markdown, CSV, HTML, PDF or Word. This model does not read pictures."
                : "Attach a picture or a document to your next message.",
            disabled: items.length >= MAX_ATTACHMENTS,
            onPress: () => input.current?.click(),
          }
        : null,
    [control, items.length],
  );

  const picker: ReactNode = control ? (
    <input
      ref={input}
      type="file"
      multiple
      hidden
      aria-label="Choose files to attach"
      accept={ATTACH_ACCEPT}
      onChange={(e) => {
        add(Array.from(e.target.files ?? []));
        e.target.value = ""; // the same file can be chosen again
      }}
    />
  ) : null;

  const chips: ReactNode = items.length ? (
    <ul aria-label="Files to attach" className="m-0 mb-2 flex list-none flex-wrap gap-2 p-0">
      {items.map((i) => (
        <AttachmentChip key={i.key} file={i} onRemove={() => remove(i.key)} />
      ))}
    </ul>
  ) : null;

  const runInput = useMemo<Record<string, unknown>>(
    () => (ready.length ? { attachments: ready.map((i) => ({ id: i.id, name: i.name })) } : {}),
    [ready],
  );
  const files = useMemo<AttachmentInfo[]>(
    () =>
      ready.map((i) => ({
        kind: i.kind,
        id: i.id,
        name: i.name,
        url: i.kind === "image" ? i.url : undefined,
      })),
    [ready],
  );

  return {
    option,
    picker,
    chips,
    busy,
    count: ready.length,
    /** the next run's input: the files that finished uploading */
    runInput,
    /** what the message will show under the person's words */
    files,
    add,
    remove,
    clear,
    /** put on the box that takes dropped files */
    dropProps: control
      ? {
          onDragOver: (e: DragEvent) => {
            if (e.dataTransfer?.types.includes("Files")) e.preventDefault();
          },
          onDrop: (e: DragEvent) => {
            const files = Array.from(e.dataTransfer?.files ?? []);
            if (!files.length) return;
            e.preventDefault();
            add(files);
          },
        }
      : {},
    /** put on the text box: a pasted file (a screenshot) is attached, pasted words are left alone */
    onPaste: control
      ? (e: ClipboardEvent) => {
          const files = Array.from(e.clipboardData?.files ?? []);
          if (!files.length) return;
          e.preventDefault();
          add(files);
        }
      : undefined,
  };
}

export type Attachments = ReturnType<typeof useAttachments>;
