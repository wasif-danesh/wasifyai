"use client";

import {
  type NotebookOutput,
  type NotebooksApi,
  type RunClient,
  type StudioFormat,
  when,
} from "@wasifyai/client";
import {
  AudioLines,
  BarChart3,
  ClipboardList,
  FileDown,
  FileText,
  Layers,
  Loader2,
  Network,
  NotebookText,
  Pencil,
  Presentation,
  RotateCw,
  Square,
  Table2,
  Trash2,
} from "lucide-react";
import { Maximize2, Minimize2 } from "lucide-react";
import { type ComponentType, useMemo, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog } from "../components/dialog";
import { type Saved, fileNameFor, savedText, useSaveCopy } from "../save";
import { OutputViewer, pictureOf } from "./OutputViewers";
import { FORMAT_LABEL, STUDIO_GROUPS, STUDIO_TILES, making } from "./outputs";
import { useNotebookPlace } from "./place";
import { useOutputs } from "./use-outputs";

const ICONS: Record<StudioFormat, ComponentType<{ className?: string }>> = {
  report: FileText,
  study_guide: NotebookText,
  flashcards: Layers,
  quiz: ClipboardList,
  mindmap: Network,
  word: FileDown,
  pdf: FileDown,
  slides: Presentation,
  datatable: Table2,
  audio: AudioLines,
  infographic: BarChart3,
};

export type StudioPaneProps = {
  api: NotebooksApi;
  runs: Pick<RunClient, "startRun">;
  notebookId: string | null;
  /** The ticked sources as `document_ids`, or undefined for every source that is ready. */
  documentIds?: string[];
  /** Why nothing can be made now (no source, no model, none ticked), or null. */
  blockedReason?: string | null;
  /** "12 sources" for the brief. */
  scopeLabel: string;
  /** A fresh link to a picture of the image product (an infographic). */
  imageUrl?: (id: string) => Promise<string>;
  /**
   * Save a picture of the library into the person's folder (the desktop window cannot download a file
   * by itself). Where it is absent (the web) the picture is fetched and saved by the browser.
   */
  saveImage?: (imageId: string, path?: string) => Promise<Saved>;
  /** The Studio is wide now, and a button toggles it (the workspace owns the width). */
  wide?: boolean;
  onToggleWide?: () => void;
};

type Ask = { kind: "delete"; output: NotebookOutput };
type Note = { tone: "ok" | "error"; text: string };

/**
 * What a notebook makes from its sources: tiles for the formats, a short brief, and the list of
 * what was made, opened in place. Outputs are made on this computer by the chat model.
 */
export function StudioPane(props: StudioPaneProps) {
  const { api, runs, notebookId, documentIds, blockedReason, scopeLabel, imageUrl, saveImage } =
    props;
  const studio = useOutputs(api, runs, notebookId);
  const hosted = useNotebookPlace() === "hosted";
  const [brief, setBrief] = useState<StudioFormat | null>(null);
  const [focus, setFocus] = useState("");
  const [open, setOpen] = useState<NotebookOutput | null>(null);
  const [asking, setAsking] = useState<Ask | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [saving, setSaving] = useState<string | null>(null); // the output being copied: one at a time
  const saveCopy = useSaveCopy();
  const copying = useRef(false); // set at once, before the screen has drawn the waiting button
  const [renaming, setRenaming] = useState<string | null>(null); // the output whose name is being changed in place
  const [draft, setDraft] = useState("");

  function finishRename(o: NotebookOutput) {
    const next = draft.trim();
    setRenaming(null);
    if (next && next !== o.title) {
      setNote(null);
      void studio.rename(o.id, next);
    }
  }

  async function create(format: StudioFormat, prompt: string) {
    setBrief(null);
    setFocus("");
    await studio.make(format, prompt, documentIds);
  }

  async function view(o: NotebookOutput) {
    if (!notebookId) return;
    setNote(null); // what was said about another output is not about this one
    try {
      setOpen(await api.output(notebookId, o.id));
    } catch {
      setOpen(o);
    }
  }

  /**
   * Keep a copy: in the app window the person chooses where in the system's Save As box and the engine writes
   * it there; on the web the browser saves it. The picture of an infographic is a picture of the library,
   * not a file of the output.
   */
  async function save(o: NotebookOutput) {
    if (!notebookId || copying.current) return;
    copying.current = true;
    setNote(null);
    setSaving(o.id);
    try {
      // the list does not carry an infographic's data, so read the output to find its picture
      const full = o.format === "infographic" && !o.data ? await api.output(notebookId, o.id) : o;
      const picture = pictureOf(full);
      if (o.format === "infographic" && !picture) throw new Error("no picture");
      const done = picture
        ? await saveCopy({
            name: fileNameFor(o.title, "png", "infographic"),
            copy: saveImage ? (path) => saveImage(picture, path) : undefined,
            blob: imageUrl
              ? async () => {
                  const res = await fetch(await imageUrl(picture));
                  if (!res.ok) throw new Error("picture");
                  return res.blob();
                }
              : undefined,
          })
        : await saveCopy({
            name: o.file_name ?? fileNameFor(o.title, "bin", "output"),
            copy: hosted ? undefined : (path) => api.exportOutput(notebookId, o.id, path),
            blob: () => api.outputFile(notebookId, o.id),
          });
      if (done) setNote({ tone: "ok", text: savedText(done) });
    } catch {
      setNote({
        tone: "error",
        text: "It could not be saved. The file may be gone: try making it again.",
      });
    } finally {
      copying.current = false;
      setSaving(null);
    }
  }

  // the open output is read again when its voices are done (kept in a ref so `overview` is stable)
  const refresh = useRef<() => void>(() => undefined);
  refresh.current = () => {
    if (open) void view(open);
  };
  const openId = open?.id;
  const openFormat = open?.format;
  const overview = useMemo(
    () =>
      openId && notebookId && openFormat === "audio"
        ? {
            state: () => api.overviewState(notebookId, openId),
            start: () => api.overviewVoices(notebookId, openId),
            audio: () => api.overviewAudio(notebookId, openId),
            changed: () => refresh.current(),
          }
        : undefined,
    [api, notebookId, openId, openFormat],
  );

  if (open) {
    const current = studio.outputs.find((o) => o.id === open.id);
    return (
      <OutputViewer
        output={{ ...open, ...(current ?? {}), body: open.body, data: open.data }}
        onBack={() => {
          setNote(null);
          setOpen(null);
        }}
        onDownload={() => void save(open)}
        imageUrl={imageUrl}
        overview={overview}
        wide={props.wide}
        onToggleWide={props.onToggleWide}
        saving={saving === open.id}
        notice={
          note ? (
            <output className={note.tone === "error" ? "text-destructive" : "text-ok"}>
              {note.text}
            </output>
          ) : null
        }
      />
    );
  }

  const blocked = blockedReason ?? null;
  return (
    <section aria-label="Studio" className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <h2 className="min-w-0 flex-1 font-medium text-sm">Studio</h2>
        {props.onToggleWide ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label={props.wide ? "Make the Studio narrower" : "Make the Studio wider"}
            title={props.wide ? "Narrower" : "Wider"}
            onClick={props.onToggleWide}
          >
            {props.wide ? <Minimize2 /> : <Maximize2 />}
          </Button>
        ) : null}
      </header>
      {note ? (
        <output
          className={cn(
            "block border-b px-4 py-2 text-sm",
            note.tone === "error" ? "text-destructive" : "text-ok",
          )}
        >
          {note.text}
        </output>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-3">
        {/* the makers in four groups by what the result is for (ADR-0093, stage U10) */}
        <div className="grid gap-3">
          {STUDIO_GROUPS.map((g) => (
            <section key={g.name} aria-label={g.name} className="grid gap-1.5">
              <h3 className="px-1 font-medium text-muted-foreground text-xs">{g.name}</h3>
              <ul className="grid grid-cols-2 gap-1.5 [&>li]:min-w-0">
                {g.keys.map((key) => {
                  const Icon = ICONS[key];
                  return (
                    <li key={key}>
                      <button
                        type="button"
                        disabled={Boolean(blocked) || studio.busy}
                        aria-pressed={brief === key}
                        onClick={() => setBrief(brief === key ? null : key)}
                        className={cn(
                          "flex h-full w-full items-center gap-2 rounded-lg border bg-card px-2.5 py-2 text-start transition-colors hover:bg-accent disabled:cursor-default disabled:opacity-60 disabled:hover:bg-card",
                          brief === key && "border-primary bg-primary/5",
                        )}
                      >
                        <Icon className="size-4 shrink-0" aria-hidden="true" />
                        <span className="min-w-0 text-sm leading-tight">{FORMAT_LABEL[key]}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
        {blocked ? <p className="mt-3 px-1 text-muted-foreground text-sm">{blocked}</p> : null}

        {brief ? (
          <form
            aria-label={`Make a ${FORMAT_LABEL[brief].toLowerCase()}`}
            className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-2 rounded-xl border p-3"
            onSubmit={(e) => {
              e.preventDefault();
              void create(brief, focus.trim());
            }}
          >
            <p className="font-medium text-sm">{FORMAT_LABEL[brief]}</p>
            <p className="text-muted-foreground text-xs">
              {STUDIO_TILES.find((t) => t.key === brief)?.about} Made from {scopeLabel}.
            </p>
            <label className="grid gap-1 text-sm">
              Focus (optional)
              <textarea
                value={focus}
                rows={2}
                maxLength={1000}
                placeholder="What should it concentrate on?"
                onChange={(e) => setFocus(e.target.value)}
                className="w-full resize-none rounded-md border bg-background p-2"
              />
            </label>
            <div className="flex gap-2">
              <Button type="submit" size="sm">
                Create
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setBrief(null)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : null}

        {studio.problem ? (
          <p role="alert" className="mt-3 text-destructive text-sm">
            {studio.problem}
          </p>
        ) : null}

        <h3 className="mt-5 mb-2 px-1 font-medium text-sm">Outputs</h3>
        {studio.outputs.length === 0 ? (
          <p className="px-1 text-muted-foreground text-sm">
            What you make is saved here, and in this notebook's search.
          </p>
        ) : (
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-2">
            {studio.outputs.map((o) => {
              const Icon = ICONS[o.format] ?? FileText;
              const name = o.title || FORMAT_LABEL[o.format];
              return (
                <li
                  key={o.id}
                  data-slot="output-card"
                  className="flex min-w-0 flex-col overflow-hidden rounded-lg border bg-card"
                >
                  <button
                    type="button"
                    tabIndex={-1}
                    aria-hidden="true"
                    disabled={o.status !== "ready"}
                    onClick={() => void view(o)}
                    className="grid h-16 place-items-center bg-muted text-muted-foreground disabled:cursor-default"
                  >
                    {making(o) ? (
                      <Loader2 className="size-6 animate-spin" />
                    ) : (
                      <Icon className="size-6" />
                    )}
                  </button>
                  <div className="grid gap-0.5 px-2.5 pt-2">
                    {renaming === o.id ? (
                      <input
                        // biome-ignore lint/a11y/noAutofocus: the person asked to rename this one
                        autoFocus
                        aria-label={`Name of ${name}`}
                        value={draft}
                        maxLength={200}
                        onChange={(e) => setDraft(e.target.value)}
                        onBlur={() => finishRename(o)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") finishRename(o);
                          if (e.key === "Escape") setRenaming(null);
                        }}
                        className="w-full rounded-md border bg-background px-1.5 py-0.5 text-sm"
                      />
                    ) : (
                      <button
                        type="button"
                        disabled={o.status === "processing"}
                        className="min-w-0 truncate text-start font-medium text-sm disabled:cursor-default"
                        title={name}
                        onClick={() => void view(o)}
                      >
                        {name}
                      </button>
                    )}
                    <span className="truncate text-muted-foreground text-xs">
                      {o.status === "processing"
                        ? (studio.step ?? "Making…")
                        : o.status === "failed"
                          ? "Failed"
                          : o.status === "cancelled"
                            ? "Stopped"
                            : `${FORMAT_LABEL[o.format]} · ${when(o.updated_at || o.created_at)}`}
                    </span>
                    {o.status === "failed" && o.error ? (
                      <p className="text-muted-foreground text-xs">{o.error}</p>
                    ) : null}
                  </div>
                  <div className="mt-auto flex items-center justify-end gap-0.5 px-1.5 py-1">
                    {making(o) ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        aria-label={`Stop ${o.title || "this"}`}
                        onClick={() => void studio.stop(o.id)}
                      >
                        <Square /> Stop
                      </Button>
                    ) : null}
                    {o.status === "failed" || o.status === "cancelled" ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        aria-label="Make it again"
                        disabled={Boolean(blocked) || studio.busy}
                        onClick={() => void studio.make(o.format, o.prompt, documentIds)}
                      >
                        <RotateCw /> Again
                      </Button>
                    ) : null}
                    {o.status === "ready" ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label={`Rename ${o.title}`}
                        title="Rename"
                        onClick={() => {
                          setDraft(o.title);
                          setRenaming(o.id);
                        }}
                      >
                        <Pencil />
                      </Button>
                    ) : null}
                    {o.has_file || o.format === "infographic" ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label={
                          o.has_file ? `Save ${o.file_name}` : `Save the picture of ${o.title}`
                        }
                        title={o.has_file ? "Save a copy" : "Save the picture"}
                        disabled={saving !== null}
                        onClick={() => void save(o)}
                      >
                        {saving === o.id ? <Loader2 className="animate-spin" /> : <FileDown />}
                      </Button>
                    ) : null}
                    {!making(o) ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label={`Delete ${o.title || "this output"}`}
                        title="Delete"
                        onClick={() => setAsking({ kind: "delete", output: o })}
                      >
                        <Trash2 />
                      </Button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {studio.busy && studio.step ? (
          <p className="mt-3 px-1 text-muted-foreground text-xs" aria-live="polite">
            {studio.step}…
          </p>
        ) : null}
        <p className="mt-4 px-1 text-muted-foreground text-xs">
          Made by the chat model{hosted ? "" : " on this computer"}, only from the sources ticked on
          the left.
        </p>
      </div>
      {asking?.kind === "delete" ? (
        <ConfirmDialog
          title="Delete this output?"
          message={`“${asking.output.title || FORMAT_LABEL[asking.output.format]}” will be deleted from this notebook.`}
          onConfirm={() => {
            void studio.remove(asking.output.id);
            setNote(null);
            setAsking(null);
          }}
          onCancel={() => setAsking(null)}
        />
      ) : null}
    </section>
  );
}
