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
import { Button } from "../../components/button";
import { Bar } from "../../components/progress-bar";
import { formatBytes } from "../../notebook/format";
import type { ComposerOption } from "../composer-options";
import { Card } from "../dictation/use-dictation";
import { AttachmentChip, type ChipData, detailOf } from "./AttachmentChip";

export const MAX_ATTACHMENTS = 4;
// how much of one document the model is given (the engine cuts at the same size): longer ones say so
const DOC_CHARS = 12_000;
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
  /** takes the person to the notebooks, for a document that is longer than the model is given */
  onOpenNotebooks?: () => void;
  /** present while the model lacks its picture reader and the app can get it: a picture then opens a card that offers it */
  pictureReader?: {
    title: string;
    licence: string;
    /** the host it comes from */
    from: string;
    bytes: number;
    /** gets it; reports how far (0 to 1, or null while unknown) and resolves when the model can read pictures */
    run(onProgress: (fraction: number | null) => void): Promise<void>;
  };
};

type Item = ChipData & { key: string };

function problem(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "That file could not be attached.";
}

export function useAttachments(control: AttachControl | undefined) {
  const [items, setItems] = useState<Item[]>([]);
  // pictures chosen before the model could read them, kept while the person decides about the picture reader
  const [held, setHeld] = useState<File[]>([]);
  const [reader, setReader] = useState<{
    state: "asking" | "working" | "failed";
    fraction: number | null;
    error: string;
  } | null>(null);
  const now = useRef<Item[]>([]);
  const seq = useRef(0);
  const previews = useRef(new Set<string>());
  const input = useRef<HTMLInputElement>(null);
  const live = useRef(control);
  live.current = control;

  const patch = useCallback((key: string, change: Partial<Item>) => {
    const next = now.current.map((i) => (i.key === key ? { ...i, ...change } : i));
    now.current = next;
    setItems(next);
  }, []);

  const forget = useCallback((i: Item) => {
    if (i.url && previews.current.delete(i.url)) URL.revokeObjectURL(i.url);
  }, []);

  // the list as of now is kept beside the state, so that effects (an upload, a preview) start once, outside any update
  const set = useCallback((next: Item[]) => {
    now.current = next;
    setItems(next);
  }, []);
  const reader_ = useRef(reader);
  reader_.current = reader;

  const add = useCallback(
    (files: File[]) => {
      const c = live.current;
      if (!c || !files.length) return;
      const next: Item[] = [...now.current];
      let room = MAX_ATTACHMENTS - next.length;
      const keep: File[] = [];
      const uploads: { key: string; file: File }[] = [];
      for (const file of files) {
        const kind = PICTURE.test(file.type) ? "image" : "document";
        const key = `a${++seq.current}`;
        const failed = (error: string) =>
          next.push({ key, kind, id: key, name: file.name, state: "failed", error });
        if (kind === "image" && c.images === false && c.pictureReader) {
          keep.push(file); // the model can be given its picture reader: ask, and attach it when it is there
          continue;
        }
        if (room <= 0) failed(`At most ${MAX_ATTACHMENTS} files fit in one message.`);
        else if (kind === "image" && c.images === false)
          failed(c.imagesNote || "This model does not read pictures.");
        else if (kind === "document" && !c.documents) failed("Files cannot be attached here.");
        else {
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
          uploads.push({ key, file });
        }
      }
      set(next);
      for (const { key, file } of uploads) {
        c.upload(file, file.name).then(
          (done) =>
            patch(key, {
              state: "ready",
              id: done.id,
              detail: detailOf({
                ...done,
                truncated: done.truncated || (done.chars ?? 0) > DOC_CHARS,
              }),
              cut: Boolean(done.truncated) || (done.chars ?? 0) > DOC_CHARS,
              name: done.name || file.name,
            }),
          (e) => patch(key, { state: "failed", error: problem(e) }),
        );
      }
      if (keep.length) {
        setHeld((h) => [...h, ...keep]);
        if (!reader_.current) setReader({ state: "asking", fraction: null, error: "" });
      }
    },
    [patch, set],
  );

  /** A document the engine already keeps (a resource of an outside server, ADR-0070): no upload. */
  const addUploaded = useCallback(
    (done: UploadedAttachment) => {
      if (now.current.length >= MAX_ATTACHMENTS) return false;
      const key = `kept-${++seq.current}`;
      const cut = Boolean(done.truncated) || (done.chars ?? 0) > DOC_CHARS;
      set([
        ...now.current,
        {
          key,
          kind: done.kind,
          id: done.id,
          name: done.name,
          state: "ready",
          detail: detailOf({ ...done, truncated: cut }),
          cut,
        },
      ]);
      return true;
    },
    [set],
  );

  const remove = useCallback(
    (key: string) => {
      const gone = now.current.find((i) => i.key === key);
      if (gone) {
        forget(gone);
        if (gone.state === "ready" && gone.id) void live.current?.discard?.(gone.id);
      }
      set(now.current.filter((i) => i.key !== key));
    },
    [forget, set],
  );

  /** After the message was sent: the files belong to it now, not to the box. */
  const clear = useCallback(() => {
    for (const i of now.current) forget(i);
    set([]);
  }, [forget, set]);

  /** The person turned the picture reader down: the pictures that waited for it are dropped. */
  const declineReader = useCallback(() => {
    setHeld([]);
    setReader(null);
  }, []);

  const getReader = useCallback(() => {
    const r = live.current?.pictureReader;
    if (!r) return;
    setReader({ state: "working", fraction: null, error: "" });
    r.run((fraction) => setReader({ state: "working", fraction, error: "" })).then(
      () => setReader(null),
      (e) => setReader({ state: "failed", fraction: null, error: problem(e) }),
    );
  }, []);

  // the model can read pictures now: the ones that waited are attached
  const sees = control?.images !== false;
  useEffect(() => {
    if (sees && held.length) {
      const wait = held;
      setHeld([]);
      setReader(null);
      add(wait);
    }
  }, [sees, held, add]);

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

  const offer = control?.pictureReader;
  const notice: ReactNode =
    reader && offer ? (
      <Card
        heading="Get the picture reader"
        actions={
          reader.state === "working" ? undefined : (
            <>
              <Button type="button" size="sm" onClick={getReader}>
                {reader.state === "failed" ? "Try again" : `Download ${formatBytes(offer.bytes)}`}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={declineReader}>
                Not now
              </Button>
            </>
          )
        }
      >
        <p className="font-medium">Get the picture reader</p>
        <p className="text-muted-foreground">
          To look at pictures this chat model needs its picture reader: {offer.title} (
          {offer.licence}){offer.from ? `, from ${offer.from}` : ""}, {formatBytes(offer.bytes)} to
          download once. It runs on this computer, so your pictures are not sent anywhere.
        </p>
        {reader.state === "working" ? (
          <div className="grid gap-1">
            <Bar value={reader.fraction ?? undefined} />
            <output className="text-muted-foreground">Getting the picture reader…</output>
          </div>
        ) : null}
        {reader.error ? <p className="text-destructive">{reader.error}</p> : null}
      </Card>
    ) : null;

  const chips: ReactNode = items.length ? (
    <ul aria-label="Files to attach" className="m-0 mb-2 flex list-none flex-wrap gap-2 p-0">
      {items.map((i) => (
        <AttachmentChip
          key={i.key}
          file={i}
          onRemove={() => remove(i.key)}
          onNotebook={control?.onOpenNotebooks}
        />
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
    /** attach a document the engine already keeps (no upload) */
    addUploaded,
    picker,
    chips,
    /** the card that offers the picture reader */
    notice,
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
