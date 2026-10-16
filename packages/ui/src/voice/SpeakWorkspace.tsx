"use client";

import {
  type ParsedEvent,
  type SavedVoice,
  type Speech,
  type VoiceApi,
  type VoiceTask,
  makeSpeech,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { ModelPicker } from "./ModelPicker";
import { OptionFields } from "./OptionFields";
import { RuntimeCard } from "./RuntimeCard";
import { clock, groupVoices, pickModel, voiceLabel } from "./format";
import { useVoiceModels } from "./use-voice-models";

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
};

/**
 * Text to speech: the model list, a voice, the text, and what was made before. The model is the
 * person's choice from the engine's list; the controls under it come from that model's descriptor.
 */
export function SpeakWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
  initialSavedVoice,
}: SpeakWorkspaceProps) {
  const [saved, setSaved] = useState<SavedVoice[]>([]);
  const [savedId, setSavedId] = useState<string | null>(initialSavedVoice ?? null);
  const savedVoice = saved.find((v) => v.id === savedId) ?? null;
  // a saved voice is spoken by the models that can design or clone; a built-in voice by the others
  const task: VoiceTask = savedVoice ? savedVoice.kind : "speak";
  const { models, runtime, error, loading, reload } = useVoiceModels(api, task);
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [voice, setVoice] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [text, setText] = useState("");
  const [step, setStep] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [speeches, setSpeeches] = useState<Speech[]>([]);
  const abort = useRef<AbortController | null>(null);

  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, task, modelId);
  const working = step !== null;

  const loadSpeeches = useCallback(
    () =>
      api
        .speeches()
        .then(setSpeeches)
        .catch(() => undefined),
    [api],
  );
  useEffect(() => {
    void loadSpeeches();
  }, [loadSpeeches]);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    api
      .voices()
      .then(setSaved)
      .catch(() => undefined);
  }, [api]);

  const voiceId = chosen?.voices.find((v) => v.id === voice)?.id ?? chosen?.default_voice ?? null;

  async function speak() {
    if (!chosen || !text.trim() || working) return;
    setProblem(null);
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
          ...(savedVoice ? { savedVoice: savedVoice.id } : voiceId ? { voice: voiceId } : {}),
          options,
        },
        abort.current.signal,
        setStep,
      );
      if (!r.ok) setProblem(r.message);
      else await loadSpeeches();
    } catch (e) {
      if (!abort.current.signal.aborted) {
        setProblem(e instanceof Error ? e.message : "That could not be made.");
      }
    } finally {
      setStep(null);
      void reload();
    }
  }

  async function remove(id: string) {
    await api.removeSpeech(id);
    setSpeeches((list) => list.filter((s) => s.id !== id));
  }

  async function save(s: Speech) {
    const blob = await api.downloadSpeech(s.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${s.text.slice(0, 40).replace(/[^\w -]+/g, "_") || "speech"}.wav`;
    a.click();
    URL.revokeObjectURL(url);
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
      {saved.length > 0 ? (
        <div className="grid gap-2">
          <Label htmlFor="speak-source">Voice</Label>
          <select
            id="speak-source"
            className="h-10 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            value={savedId ?? ""}
            disabled={working}
            onChange={(e) => {
              setSavedId(e.target.value || null);
              setModelId(null);
              setValues({});
            }}
          >
            <option value="">A voice that comes with the model</option>
            <optgroup label="Your voices">
              {saved.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} ({v.kind === "design" ? "described" : "cloned"})
                </option>
              ))}
            </optgroup>
          </select>
        </div>
      ) : null}
      <ModelPicker
        models={models}
        task={task}
        value={chosen?.id ?? null}
        onChange={(id) => {
          setModelId(id);
          setVoice(null);
          setValues({});
          onModelChosen?.(id);
        }}
        onGetModel={onGetModel}
        disabled={working}
      />
      {chosen && !savedVoice && chosen.voices.length > 0 ? (
        <div className="grid gap-2">
          <Label htmlFor="speak-voice">Built-in voice</Label>
          <select
            id="speak-voice"
            className="h-10 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            value={voiceId ?? ""}
            disabled={working}
            onChange={(e) => setVoice(e.target.value)}
          >
            {groupVoices(chosen.voices).map((g) => (
              <optgroup key={g.label} label={g.label}>
                {g.voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {voiceLabel(v)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
      ) : null}
      {chosen ? (
        <OptionFields
          options={chosen.options}
          values={values}
          onChange={(name, v) => setValues((prev) => ({ ...prev, [name]: v }))}
          disabled={working}
        />
      ) : null}
      <div className="grid gap-2">
        <Label htmlFor="speak-text">Text</Label>
        <Textarea
          id="speak-text"
          rows={5}
          value={text}
          maxLength={5000}
          placeholder="Type what you want to hear"
          disabled={working}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => void speak()} disabled={!ready || working || !text.trim()}>
          {working ? "Making it…" : "Speak"}
        </Button>
        {working ? (
          <>
            <output className="flex items-center gap-2 text-muted-foreground text-sm">
              <Spinner /> {step}
            </output>
            <Button variant="ghost" onClick={() => abort.current?.abort()}>
              Cancel
            </Button>
          </>
        ) : null}
        {!ready && chosen ? (
          <span className="text-muted-foreground text-sm">
            Set this model up first (see above).
          </span>
        ) : null}
      </div>
      {problem ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}
      {speeches.length > 0 ? (
        <section aria-label="Made before" className="grid gap-3">
          <h2 className="font-semibold">Made before</h2>
          <ul className="grid gap-3">
            {speeches.map((s) => (
              <li key={s.id} className="grid gap-2 rounded-xl border bg-card p-3">
                <p className="line-clamp-2">{s.text}</p>
                {/* biome-ignore lint/a11y/useMediaCaption: the text above is the transcript */}
                <audio controls preload="none" src={s.audio_url} className="h-10 w-full" />
                <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-xs">
                  <span>{clock(s.seconds)}</span>
                  <span>{models.find((m) => m.id === s.model_id)?.title ?? s.model_id}</span>
                  <span className="ms-auto flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => void save(s)}>
                      Save
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => void remove(s.id)}>
                      Delete
                    </Button>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
