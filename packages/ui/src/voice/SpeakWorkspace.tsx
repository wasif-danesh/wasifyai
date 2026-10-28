"use client";

import {
  type ParsedEvent,
  type SavedVoice,
  type Speech,
  type VoiceApi,
  type VoiceTask,
  makeSpeech,
} from "@wasifyai/client";
import { AudioLines, Pencil, Save, Shuffle, Trash2 } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { Action } from "../components/actions-row";
import { Button } from "../components/button";
import { ConfirmDialog, Modal } from "../components/dialog";
import { Experts } from "../components/experts";
import { Label } from "../components/label";
import { MakeScreen } from "../components/make-screen";
import { Player } from "../components/player";
import { type RecentItem, RecentStrip } from "../components/recent-strip";
import { Spinner } from "../components/spinner";
import { Stage, type StageState } from "../components/stage";
import { Textarea } from "../components/textarea";
import { fileNameFor, savedText, useSaveCopy } from "../save";
import { appearsHere, makeLabel, makingLabel } from "../words";
import { LoadingModels, ModelPicker, NotReadyText } from "./ModelPicker";
import { OptionFields, expertsSummary } from "./OptionFields";
import { RuntimeCard } from "./RuntimeCard";
import { type VoiceChoice, VoicesPanel } from "./VoicesPanel";
import { SAMPLE, VoicesWorkspace } from "./VoicesWorkspace";
import { clock, pickModel } from "./format";
import { useVoiceModels } from "./use-voice-models";

const MAX_TEXT = 5000;

export type SpeakWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  /** open the Models panel for a model that is not on this computer */
  onGetModel?: (id: string) => void;
  /** remembered between visits by the app (optional) */
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
  /** a voice the person saved, chosen from the Voices screen */
  initialSavedVoice?: string | null;
  /** the screen's heading and the line under it */
  title?: string;
  lead?: string;
  /** take a speech to Change a voice or Edit speech (the app opens that screen with it chosen) */
  onTool?: (speech: Speech, tool: "convert" | "edit") => void;
  /** "See all" on the recent strip */
  onOpenLibrary?: () => void;
};

/**
 * Text to speech on the one make screen (ADR-0093, stage U5): the words and the voice on the left, chosen by
 * hearing them in the voices panel; the speech plays on the stage with its waveform; what was spoken before is
 * the recent strip. The model is the person's choice from the engine's list (in the top bar in the window); its
 * own settings (speed, seed) are under "For experts".
 */
export function SpeakWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
  initialSavedVoice,
  title = "Text to speech",
  lead,
  onTool,
  onOpenLibrary,
}: SpeakWorkspaceProps) {
  const textId = useId();
  const [saved, setSaved] = useState<SavedVoice[]>([]);
  const [choice, setChoice] = useState<VoiceChoice | null>(
    initialSavedVoice ? { kind: "saved", id: initialSavedVoice } : null,
  );
  const savedVoice =
    choice?.kind === "saved" ? (saved.find((v) => v.id === choice.id) ?? null) : null;
  // a saved voice is spoken by the models that can design or clone; a built-in voice by the others
  const task: VoiceTask = savedVoice ? savedVoice.kind : "speak";
  const { models, runtime, error, loading, reload } = useVoiceModels(api, task);
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [text, setText] = useState("");
  const [step, setStep] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [speeches, setSpeeches] = useState<Speech[] | null>(null);
  const [shownId, setShownId] = useState<string | null>(null);
  const [savedLine, setSavedLine] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Speech | null>(null);
  const [makingVoice, setMakingVoice] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, task, modelId);
  const working = step !== null;

  const loadSpeeches = useCallback(
    () =>
      api
        .speeches()
        .then(setSpeeches)
        .catch(() => setSpeeches((s) => s ?? [])),
    [api],
  );
  const loadVoices = useCallback(
    () =>
      api
        .voices()
        .then(setSaved)
        .catch(() => undefined),
    [api],
  );
  useEffect(() => {
    void loadSpeeches();
  }, [loadSpeeches]);
  useEffect(() => {
    void loadVoices();
  }, [loadVoices]);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (!working) return;
    setWaited(0);
    const t = setInterval(() => setWaited((w) => w + 1), 1000);
    return () => clearInterval(t);
  }, [working]);

  const builtInId =
    choice?.kind === "builtin" && chosen?.voices.some((v) => v.id === choice.id)
      ? choice.id
      : (chosen?.default_voice ?? null);
  const panelValue: VoiceChoice | null = savedVoice
    ? { kind: "saved", id: savedVoice.id }
    : builtInId
      ? { kind: "builtin", id: builtInId }
      : null;

  function chooseVoice(next: VoiceChoice) {
    const wasSaved = choice?.kind === "saved";
    setChoice(next);
    // a saved voice and a built-in one are spoken by different models
    if (wasSaved !== (next.kind === "saved")) {
      setModelId(null);
      setValues({});
    }
  }

  async function speak() {
    if (!chosen || !text.trim() || working) return;
    setProblem(null);
    setSavedLine(null);
    setStep("Starting");
    abort.current = new AbortController();
    const options = Object.fromEntries(
      Object.entries(values).filter(
        ([k, v]) => v !== undefined && chosen.options.some((o) => o.name === k),
      ),
    );
    try {
      const r = await makeSpeech(
        runs,
        {
          text,
          model: chosen.id,
          ...(savedVoice ? { savedVoice: savedVoice.id } : builtInId ? { voice: builtInId } : {}),
          options,
        },
        abort.current.signal,
        setStep,
      );
      if (!r.ok) setProblem(r.message);
      else {
        setShownId(r.speech.id);
        await loadSpeeches();
      }
    } catch (e) {
      if (!abort.current.signal.aborted) {
        setProblem(e instanceof Error ? e.message : "That could not be made.");
      }
    } finally {
      setStep(null);
      void reload();
    }
  }

  async function sample(c: VoiceChoice): Promise<string | null> {
    try {
      const r = await makeSpeech(
        runs,
        c.kind === "saved"
          ? { text: SAMPLE, savedVoice: c.id }
          : { text: SAMPLE, model: chosen?.id, voice: c.id },
        new AbortController().signal,
      );
      if (!r.ok) {
        setProblem(r.message);
        return null;
      }
      void loadSpeeches();
      return r.speech.audio_url;
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be made.");
      return null;
    }
  }

  async function remove(s: Speech) {
    setDeleting(null);
    try {
      await api.removeSpeech(s.id);
      setSpeeches((list) => (list ?? []).filter((x) => x.id !== s.id));
      if (shownId === s.id) setShownId(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be deleted.");
    }
  }

  const saveCopy = useSaveCopy();
  async function save(s: Speech) {
    setProblem(null);
    try {
      const out = await saveCopy({
        name: fileNameFor(s.text.slice(0, 40), "wav", "speech"),
        blob: () => api.downloadSpeech(s.id),
      });
      if (out) setSavedLine(savedText(out));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be saved.");
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

  const ready = chosen?.state === "ready";
  const shown = speeches?.find((s) => s.id === shownId) ?? null;
  const modelTitle = (id: string) => models.find((m) => m.id === id)?.title ?? id;

  const actions: Action[] = shown
    ? [
        {
          label: "Save a copy",
          onSelect: () => void save(shown),
          icon: <Save aria-hidden="true" />,
        },
        { label: "Use these words", onSelect: () => setText(shown.text.slice(0, MAX_TEXT)) },
        ...(onTool
          ? [
              {
                label: "Change the voice",
                onSelect: () => onTool(shown, "convert"),
                icon: <Shuffle aria-hidden="true" />,
              },
              {
                label: "Edit the words",
                onSelect: () => onTool(shown, "edit"),
                icon: <Pencil aria-hidden="true" />,
              },
            ]
          : []),
        {
          label: "Delete",
          onSelect: () => setDeleting(shown),
          icon: <Trash2 aria-hidden="true" />,
          destructive: true,
        },
      ]
    : [];

  const stage: StageState = working
    ? {
        kind: "working",
        label: makingLabel("speech"),
        text: `${step} · ${clock(waited)}`,
        onStop: () => abort.current?.abort(),
      }
    : problem && !shown
      ? { kind: "error", message: problem, onReset: () => setProblem(null) }
      : shown
        ? {
            kind: "result",
            children: (
              <Player
                key={shown.id}
                className="w-full"
                src={shown.audio_url}
                title={shown.text.slice(0, 60)}
                duration={shown.seconds}
                waveform
              />
            ),
            caption: (
              <div className="grid gap-1">
                <p className="m-0 line-clamp-4 text-foreground">{shown.text}</p>
                <span className="text-xs">
                  {clock(shown.seconds)} · {modelTitle(shown.model_id)}
                </span>
                {savedLine ? <output className="text-sm">{savedLine}</output> : null}
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
            icon: AudioLines,
            title: appearsHere("speech"),
            text: "Type the words and choose a voice on the left, then press Make the speech.",
          };

  const recent: RecentItem[] = (speeches ?? []).slice(0, 24).map((s) => ({
    id: s.id,
    cover: (
      <span className="grid size-full place-items-center gap-0.5 bg-muted p-1 text-center">
        <AudioLines className="size-4 text-muted-foreground" aria-hidden="true" />
        <span className="line-clamp-2 text-[0.625rem] leading-tight">{s.text}</span>
      </span>
    ),
    label: `Open: ${s.text.slice(0, 80)}`,
    current: s.id === shownId,
    onOpen: () => {
      if (working) return;
      setProblem(null);
      setSavedLine(null);
      setShownId(s.id);
    },
  }));

  return (
    <>
      <MakeScreen
        title={title}
        lead={lead}
        ask={
          <>
            {runtime ? <RuntimeCard runtime={runtime} api={api} onChanged={reload} /> : null}
            <ModelPicker
              models={models}
              task={task}
              value={chosen?.id ?? null}
              onChange={(id) => {
                setModelId(id);
                setValues({});
                onModelChosen?.(id);
              }}
              onGetModel={onGetModel}
              disabled={working}
            />
            <div className="grid gap-2">
              <Label htmlFor={textId} className="font-semibold text-ui-lg">
                What should it say?
              </Label>
              <Textarea
                id={textId}
                rows={7}
                className="min-h-40"
                value={text}
                maxLength={MAX_TEXT}
                placeholder="Type the words you want to hear, in any language the model speaks"
                disabled={working}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    void speak();
                  }
                }}
              />
              <span className="text-end text-muted-foreground text-xs tabular-nums">
                {text.length}/{MAX_TEXT}
              </span>
            </div>
            <VoicesPanel
              builtIn={savedVoice ? [] : (chosen?.voices ?? [])}
              saved={saved}
              value={panelValue}
              onChange={chooseVoice}
              speeches={speeches ?? []}
              modelId={chosen?.id ?? null}
              onSample={ready || savedVoice ? sample : undefined}
              onMakeVoice={() => setMakingVoice(true)}
              disabled={working}
            />
            {chosen && chosen.options.length > 0 ? (
              <Experts summary={expertsSummary(chosen.options)}>
                <OptionFields
                  options={chosen.options}
                  values={values}
                  onChange={(name, v) => setValues((prev) => ({ ...prev, [name]: v }))}
                  disabled={working}
                />
              </Experts>
            ) : null}
          </>
        }
        action={
          <>
            <Button
              type="button"
              size="lg"
              className="w-full rounded-full md:w-auto md:px-10"
              disabled={!ready || working || !text.trim()}
              title="Ctrl or ⌘ + Enter makes it too"
              aria-keyshortcuts="Control+Enter Meta+Enter"
              onClick={() => void speak()}
            >
              {working ? <Spinner /> : null}
              {makeLabel("speech")}
            </Button>
            {!ready && chosen ? (
              <p className="mt-2 text-muted-foreground text-xs">
                <NotReadyText task="speak" seeAbove />
              </p>
            ) : null}
          </>
        }
        stage={<Stage state={stage} className="w-full" minHeight="min-h-[14rem]" />}
        recent={
          <RecentStrip
            title="Recent speech"
            items={recent}
            loading={speeches === null}
            onSeeAll={onOpenLibrary}
            empty="Nothing spoken yet. Your first speech will show up here."
          />
        }
      />
      {deleting ? (
        <ConfirmDialog
          title="Delete this speech?"
          message={`“${deleting.text.slice(0, 80)}” is deleted for good.`}
          onConfirm={() => void remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      ) : null}
      {makingVoice ? (
        <Modal label="Make a voice" wide onClose={() => setMakingVoice(false)}>
          <VoicesWorkspace
            api={api}
            runs={runs}
            onUseVoice={(id) => {
              void loadVoices();
              chooseVoice({ kind: "saved", id });
              setMakingVoice(false);
            }}
          />
        </Modal>
      ) : null}
    </>
  );
}
