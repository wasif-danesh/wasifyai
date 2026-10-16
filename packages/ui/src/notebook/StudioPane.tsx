"use client";

import type { NotebookOutput, NotebooksApi, RunClient, StudioFormat } from "@wasifyai/client";
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
import { type ComponentType, useMemo, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { OutputViewer } from "./OutputViewers";
import { FORMAT_LABEL, STUDIO_TILES, making } from "./outputs";
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
};

/**
 * What a notebook makes from its sources: tiles for the formats, a short brief, and the list of
 * what was made, opened in place. Outputs are made on this computer by the chat model.
 */
export function StudioPane(props: StudioPaneProps) {
  const { api, runs, notebookId, documentIds, blockedReason, scopeLabel, imageUrl } = props;
  const studio = useOutputs(api, runs, notebookId);
  const [brief, setBrief] = useState<StudioFormat | null>(null);
  const [focus, setFocus] = useState("");
  const [open, setOpen] = useState<NotebookOutput | null>(null);

  async function create(format: StudioFormat, prompt: string) {
    setBrief(null);
    setFocus("");
    await studio.make(format, prompt, documentIds);
  }

  async function view(o: NotebookOutput) {
    if (!notebookId) return;
    try {
      setOpen(await api.output(notebookId, o.id));
    } catch {
      setOpen(o);
    }
  }

  async function save(o: NotebookOutput) {
    if (!notebookId) return;
    try {
      const blob = await api.outputFile(notebookId, o.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = o.file_name ?? "output";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch {
      // the list shows nothing new: the file may be gone
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
        onBack={() => setOpen(null)}
        onDownload={() => void save(open)}
        imageUrl={imageUrl}
        overview={overview}
      />
    );
  }

  const blocked = blockedReason ?? null;
  return (
    <section aria-label="Studio" className="flex h-full min-h-0 flex-col">
      <header className="border-b px-4 py-3">
        <h2 className="font-medium text-sm">Studio</h2>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-3">
        <ul className="grid grid-cols-2 gap-2 [&>li]:min-w-0">
          {STUDIO_TILES.map((t) => {
            const Icon = ICONS[t.key];
            return (
              <li key={t.key}>
                <button
                  type="button"
                  disabled={Boolean(blocked) || studio.busy}
                  aria-pressed={brief === t.key}
                  onClick={() => setBrief(brief === t.key ? null : t.key)}
                  className={cn(
                    "flex h-full w-full flex-col items-start gap-2 rounded-xl border bg-card p-3 text-start transition-colors hover:bg-accent disabled:cursor-default disabled:opacity-60 disabled:hover:bg-card",
                    brief === t.key && "border-primary bg-primary/5",
                  )}
                >
                  <Icon className="size-5" aria-hidden="true" />
                  <span className="text-sm">{t.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
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
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
            {studio.outputs.map((o) => {
              const Icon = ICONS[o.format] ?? FileText;
              return (
                <li key={o.id} className="group rounded-lg border">
                  <div className="flex items-center gap-2 px-2.5 py-2">
                    {making(o) ? (
                      <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />
                    ) : (
                      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    )}
                    <button
                      type="button"
                      disabled={o.status === "processing"}
                      className="min-w-0 flex-1 truncate text-start text-sm disabled:cursor-default"
                      title={o.title || FORMAT_LABEL[o.format]}
                      onClick={() => void view(o)}
                    >
                      {o.title || FORMAT_LABEL[o.format]}
                    </button>
                    <span className="shrink-0 text-muted-foreground text-xs">
                      {o.status === "processing"
                        ? (studio.step ?? "Making…")
                        : o.status === "failed"
                          ? "Failed"
                          : o.status === "cancelled"
                            ? "Stopped"
                            : FORMAT_LABEL[o.format]}
                    </span>
                  </div>
                  {o.status === "failed" && o.error ? (
                    <p className="px-2.5 pb-1.5 text-muted-foreground text-xs">{o.error}</p>
                  ) : null}
                  <div className="hidden items-center justify-end gap-0.5 px-1.5 pb-1.5 group-focus-within:flex group-hover:flex">
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
                        onClick={() => {
                          const next = window.prompt("Name this output", o.title)?.trim();
                          if (next && next !== o.title) void studio.rename(o.id, next);
                        }}
                      >
                        <Pencil />
                      </Button>
                    ) : null}
                    {o.has_file ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label={`Save ${o.file_name}`}
                        onClick={() => void save(o)}
                      >
                        <FileDown />
                      </Button>
                    ) : null}
                    {!making(o) ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label={`Delete ${o.title || "this output"}`}
                        onClick={() => {
                          if (window.confirm(`Delete “${o.title || FORMAT_LABEL[o.format]}”?`))
                            void studio.remove(o.id);
                        }}
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
          Made by the chat model on this computer, only from the sources ticked on the left.
        </p>
      </div>
    </section>
  );
}
