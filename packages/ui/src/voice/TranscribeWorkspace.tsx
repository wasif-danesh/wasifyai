"use client";

import type { Transcript, TranscriptFormat, VoiceApi } from "@wasifyai/client";
import { Copy, FileAudio, FileText, Save, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "../cn";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { ConfirmDialog } from "../components/dialog";
import { MakeScreen } from "../components/make-screen";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Spinner } from "../components/spinner";
import { Stage, type StageState } from "../components/stage";
import { usePictureEvents } from "../hooks/use-picture-events";
import type { ModelSelectHandle } from "../models";
import { fileNameFor, savedText, useSaveCopy } from "../save";
import { DETECT, LanguageField, NoModelSpeaks, TELL_THE_MODEL, modelsFor } from "./LanguageField";
import { LoadingModels, ModelPicker, NotReadyText } from "./ModelPicker";
import { RuntimeCard } from "./RuntimeCard";
import { clock, pickModel } from "./format";
import { languageName } from "./languages";
import { useVoiceModels } from "./use-voice-models";

export const AUDIO_ACCEPT = "audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.caf,.aiff";

export type TranscribeWorkspaceProps = {
  api: VoiceApi;
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
  /** the language last used on a voice screen, and where a chosen one is kept (both optional) */
  initialLanguage?: string | null;
  onLanguageChosen?: (code: string) => void;
  title?: string;
  lead?: string;
};

/**
 * Speech to text on the one make screen (ADR-0093, stage U5): the recording on the left (drop it or choose it),
 * the text with its times on the stage with Copy and Save, the transcripts made before in the recent strip.
 */
export function TranscribeWorkspace({
  api,
  onGetModel,
  initialModel,
  onModelChosen,
  initialLanguage,
  onLanguageChosen,
  title = "Speech to text",
  lead,
}: TranscribeWorkspaceProps) {
  const { models, runtime, error, loading, reload } = useVoiceModels(api, "transcribe");
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [waited, setWaited] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [items, setItems] = useState<Transcript[] | null>(null);
  const [open, setOpen] = useState<Transcript | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Transcript | null>(null);
  const input = useRef<HTMLInputElement>(null);
  // what the recording is in (voice languages plan, stage L4): it filters the models; "Find it by
  // itself" leaves it to the model, which is unsafe for Bengali and Hindi, so those are always sent
  const [language, setLanguage] = useState(initialLanguage || DETECT);
  const picker = useRef<ModelSelectHandle>(null);
  const detecting = language === DETECT;
  const usable = detecting ? models : modelsFor(models, language);
  const chosen = usable.find((m) => m.id === modelId) ?? pickModel(usable, "transcribe", modelId);
  const noneReady = !detecting && !usable.some((m) => m.state === "ready");
  const ready = chosen?.state === "ready";

  const load = useCallback(
    () =>
      api
        .transcripts()
        .then(setItems)
        .catch(() => setItems((i) => i ?? [])),
    [api],
  );
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!busy) return;
    setWaited(0);
    const t = setInterval(() => setWaited((w) => w + 1), 1000);
    return () => clearInterval(t);
  }, [busy]);
  const { dragging } = usePictureEvents((f) => !busy && setFile(f), !loading && !error);

  async function transcribe() {
    if (!chosen || !file || busy) return;
    setProblem(null);
    setNote(null);
    setBusy(true);
    try {
      const t = await api.transcribe(file, chosen.id, undefined, detecting ? undefined : language);
      setOpen(t);
      setFile(null);
      await load();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be transcribed.");
    } finally {
      setBusy(false);
      void reload();
    }
  }

  async function show(id: string) {
    setProblem(null);
    setNote(null);
    try {
      setOpen(await api.transcript(id));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That transcript could not be opened.");
    }
  }

  const saveCopy = useSaveCopy();
  async function save(t: Transcript, format: TranscriptFormat) {
    setProblem(null);
    try {
      const out = await saveCopy({
        name: fileNameFor(t.title, format, "transcript"),
        blob: () => api.exportTranscript(t.id, format),
      });
      if (out) setNote(savedText(out));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be saved.");
    }
  }

  async function remove(t: Transcript) {
    setDeleting(null);
    try {
      await api.removeTranscript(t.id);
      setItems((list) => (list ?? []).filter((x) => x.id !== t.id));
      setOpen((o) => (o?.id === t.id ? null : o));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be deleted.");
    }
  }

  if (error) {
    return (
      <p role="alert" className="p-6 text-destructive">
        {error}
      </p>
    );
  }
  if (loading) return <LoadingModels />;

  const actions: Action[] = open
    ? [
        {
          label: "Copy",
          onSelect: () => {
            void navigator.clipboard?.writeText(open.text);
            setNote("Copied.");
          },
          icon: <Copy aria-hidden="true" />,
        },
        {
          label: "Save .txt",
          onSelect: () => void save(open, "txt"),
          icon: <Save aria-hidden="true" />,
        },
        { label: "Save .srt", onSelect: () => void save(open, "srt") },
        { label: "Save .vtt", onSelect: () => void save(open, "vtt") },
        {
          label: "Delete",
          onSelect: () => setDeleting(open),
          icon: <Trash2 aria-hidden="true" />,
          destructive: true,
        },
      ]
    : [];

  const stage: StageState = busy
    ? {
        kind: "working",
        label: "Transcribing your recording…",
        text: `${file?.name ?? ""} · ${clock(waited)}`,
      }
    : problem && !open
      ? { kind: "error", message: problem, onReset: () => setProblem(null) }
      : open
        ? {
            kind: "result",
            children: (
              <article aria-label="Transcript" className="grid w-full gap-3 text-start">
                <h2 className="m-0 font-semibold">{open.title}</h2>
                {open.segments.length > 0 ? (
                  <ol className="m-0 grid max-h-[calc(100dvh-24rem)] list-none gap-1.5 overflow-auto p-0">
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
                  <p className="m-0">{open.text}</p>
                )}
              </article>
            ),
            caption: (
              <div className="grid gap-1">
                <span className="text-xs">
                  {clock(open.seconds)} · {open.source_name}
                </span>
                {note ? <output className="text-sm">{note}</output> : null}
                {problem ? (
                  <p role="alert" className="m-0 text-destructive text-sm">
                    {problem}
                  </p>
                ) : null}
              </div>
            ),
            actions,
          }
        : {
            kind: "empty",
            icon: FileText,
            title: "Your transcript appears here.",
            text: "Choose a recording on the left, then press Transcribe.",
          };

  const recent: RecentItem[] = (items ?? []).slice(0, 24).map((t) => ({
    id: t.id,
    cover: (
      <span className="grid size-full place-items-center gap-0.5 bg-muted p-1 text-center">
        <FileText className="size-4 text-muted-foreground" aria-hidden="true" />
        <span className="line-clamp-2 text-xs leading-tight">{t.title}</span>
      </span>
    ),
    label: `Open: ${t.title}`,
    current: open?.id === t.id,
    onOpen: () => void show(t.id),
  }));

  return (
    <>
      <MakeScreen
        title={title}
        lead={lead}
        ask={
          <>
            {runtime ? <RuntimeCard runtime={runtime} api={api} onChanged={reload} /> : null}
            <LanguageField
              models={models}
              value={language}
              ready="Ready to write down"
              detect
              onChange={(code) => {
                setLanguage(code);
                if (code !== DETECT) onLanguageChosen?.(code);
              }}
              disabled={busy}
            />
            {detecting ? (
              <p className="-mt-2 m-0 text-muted-foreground text-xs">
                In {TELL_THE_MODEL.map(languageName).join(" or ")}? Choose it: a model finding the
                language by itself mixes them up.
              </p>
            ) : null}
            {noneReady ? (
              <NoModelSpeaks
                language={language}
                verb="writes down"
                task="transcribe"
                models={usable}
                onUse={(id) => {
                  setModelId(id);
                  onModelChosen?.(id);
                }}
                onGetModel={onGetModel}
                onOpenModels={() => picker.current?.open()}
              />
            ) : null}
            <ModelPicker
              handleRef={picker}
              models={usable}
              task="transcribe"
              value={chosen?.id ?? null}
              onChange={(id) => {
                setModelId(id);
                onModelChosen?.(id);
              }}
              onGetModel={onGetModel}
              disabled={busy}
            />
            <section className="grid gap-2" aria-label="Recording">
              <h2 className="m-0 font-semibold text-ui-lg">Your recording</h2>
              <input
                id="transcribe-file"
                ref={input}
                type="file"
                accept={AUDIO_ACCEPT}
                className="sr-only"
                aria-label="Choose a recording"
                disabled={busy}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) setFile(f);
                }}
              />
              {file ? (
                <div className="flex items-center gap-3 rounded-md border p-3">
                  <FileAudio className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate text-sm">{file.name}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => setFile(null)}
                  >
                    Remove
                  </Button>
                </div>
              ) : (
                <div
                  data-dragging={dragging || undefined}
                  className={cn(
                    "grid justify-items-center gap-2 rounded-md border border-dashed px-4 py-6 text-center text-muted-foreground text-sm",
                    "data-[dragging]:border-primary data-[dragging]:bg-accent",
                  )}
                >
                  <FileAudio className="size-5" aria-hidden="true" />
                  <p className="m-0">Drop a recording here, or</p>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => input.current?.click()}
                  >
                    <Upload aria-hidden="true" /> Choose a recording
                  </Button>
                </div>
              )}
              <p className="m-0 text-muted-foreground text-xs">
                WAV, MP3, M4A, FLAC or OGG. The text keeps the times, for subtitles.
              </p>
            </section>
          </>
        }
        action={
          <>
            <Button
              type="button"
              size="lg"
              className="w-full rounded-full md:w-auto md:px-10"
              disabled={!ready || !file || busy}
              onClick={() => void transcribe()}
            >
              {busy ? <Spinner /> : null}
              Transcribe
            </Button>
            {!ready && chosen && !noneReady ? (
              <p className="mt-2 text-muted-foreground text-xs">
                <NotReadyText task="transcribe" seeAbove />
              </p>
            ) : null}
          </>
        }
        stage={<Stage state={stage} className="w-full" />}
        recent={
          <RecentStrip
            title="Recent transcripts"
            items={recent}
            loading={items === null}
            empty="Nothing transcribed yet. Your first transcript will show up here."
          />
        }
      />
      {deleting ? (
        <ConfirmDialog
          title="Delete this transcript?"
          message={`“${deleting.title}” is deleted for good.`}
          onConfirm={() => void remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      ) : null}
    </>
  );
}
