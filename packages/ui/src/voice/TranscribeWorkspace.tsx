"use client";

import type { Transcript, TranscriptFormat, VoiceApi } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { ModelPicker } from "./ModelPicker";
import { RuntimeCard } from "./RuntimeCard";
import { clock, pickModel } from "./format";
import { useVoiceModels } from "./use-voice-models";

export const AUDIO_ACCEPT = "audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.caf,.aiff";

export type TranscribeWorkspaceProps = {
  api: VoiceApi;
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
};

/** Speech to text: choose a model and a recording, read the text with its times, save it as text or
 * subtitles. Transcripts are kept and found again in the list. */
export function TranscribeWorkspace({
  api,
  onGetModel,
  initialModel,
  onModelChosen,
}: TranscribeWorkspaceProps) {
  const { models, runtime, error, loading, reload } = useVoiceModels(api, "transcribe");
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [items, setItems] = useState<Transcript[]>([]);
  const [open, setOpen] = useState<Transcript | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, "transcribe", modelId);

  const load = useCallback(
    () =>
      api
        .transcripts()
        .then(setItems)
        .catch(() => undefined),
    [api],
  );
  useEffect(() => {
    void load();
  }, [load]);

  async function transcribe(file: File) {
    if (!chosen || busy) return;
    setProblem(null);
    setBusy(file.name);
    try {
      const t = await api.transcribe(file, chosen.id);
      setOpen(t);
      await load();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be transcribed.");
    } finally {
      setBusy(null);
      void reload();
    }
  }

  async function show(id: string) {
    setOpen(await api.transcript(id));
  }

  async function save(t: Transcript, format: TranscriptFormat) {
    const blob = await api.exportTranscript(t.id, format);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${t.title.replace(/[^\w -]+/g, "_") || "transcript"}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function remove(id: string) {
    await api.removeTranscript(id);
    setItems((list) => list.filter((t) => t.id !== id));
    setOpen((o) => (o?.id === id ? null : o));
  }

  if (error) {
    return (
      <p role="alert" className="text-destructive">
        {error}
      </p>
    );
  }
  if (loading) return <Spinner />;
  const ready = chosen?.state === "ready";

  return (
    <div className="mx-auto grid w-full min-w-0 max-w-3xl gap-6">
      {runtime ? <RuntimeCard runtime={runtime} api={api} onChanged={reload} /> : null}
      <ModelPicker
        models={models}
        task="transcribe"
        value={chosen?.id ?? null}
        onChange={(id) => {
          setModelId(id);
          onModelChosen?.(id);
        }}
        onGetModel={onGetModel}
        disabled={busy !== null}
      />
      <div
        className={`grid justify-items-center gap-2 rounded-2xl border-2 border-dashed p-8 text-center ${drag ? "border-primary bg-primary/5" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const f = e.dataTransfer.files[0];
          if (f) void transcribe(f);
        }}
      >
        <Label htmlFor="transcribe-file" className="sr-only">
          Recording
        </Label>
        <input
          id="transcribe-file"
          ref={input}
          type="file"
          accept={AUDIO_ACCEPT}
          className="sr-only"
          disabled={!ready || busy !== null}
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) void transcribe(f);
          }}
        />
        {busy ? (
          <output className="flex items-center gap-2">
            <Spinner /> Reading {busy}…
          </output>
        ) : (
          <>
            <p>Drop a recording here, or</p>
            <Button disabled={!ready} onClick={() => input.current?.click()}>
              Choose a recording
            </Button>
            {!ready && chosen ? (
              <p className="text-muted-foreground text-sm">Set this model up first (see above).</p>
            ) : null}
          </>
        )}
      </div>
      {problem ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}
      {open ? (
        <article aria-label="Transcript" className="grid gap-3 rounded-2xl border bg-card p-4">
          <header className="flex flex-wrap items-center gap-2">
            <h2 className="me-auto font-semibold">{open.title}</h2>
            <span className="text-muted-foreground text-xs">{clock(open.seconds)}</span>
            {(["txt", "srt", "vtt"] as const).map((f) => (
              <Button key={f} size="sm" variant="outline" onClick={() => void save(open, f)}>
                Save .{f}
              </Button>
            ))}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void navigator.clipboard?.writeText(open.text)}
            >
              Copy
            </Button>
          </header>
          {open.segments.length > 0 ? (
            <ol className="grid gap-1.5">
              {open.segments.map((s) => (
                <li key={`${s.start}-${s.end}`} className="grid grid-cols-[3.5rem_1fr] gap-2">
                  <time className="text-muted-foreground text-xs tabular-nums">
                    {clock(s.start)}
                  </time>
                  <span>{s.text}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p>{open.text}</p>
          )}
        </article>
      ) : null}
      {items.length > 0 ? (
        <section aria-label="Earlier transcripts" className="grid gap-2">
          <h2 className="font-semibold">Earlier</h2>
          <ul className="grid gap-2">
            {items.map((t) => (
              <li key={t.id} className="flex items-center gap-2 rounded-xl border bg-card p-3">
                <button
                  type="button"
                  className="min-w-0 flex-1 text-start"
                  onClick={() => void show(t.id)}
                >
                  <span className="block truncate font-medium">{t.title}</span>
                  <span className="block truncate text-muted-foreground text-sm">{t.text}</span>
                </button>
                <Button size="sm" variant="ghost" onClick={() => void remove(t.id)}>
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
