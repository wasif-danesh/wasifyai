"use client";

import {
  type MusicMode,
  type MusicModeRules,
  type ParsedEvent,
  type VoiceApi,
  makeTrack,
} from "@wasifyai/client";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { ModelPicker } from "./ModelPicker";
import { OptionFields } from "./OptionFields";
import { RuntimeCard } from "./RuntimeCard";
import { TrackList } from "./TrackList";
import { clock, pickModel } from "./format";
import { useVoiceModels } from "./use-voice-models";

export type MusicWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
};

const MODE_TEXT: Record<MusicMode, { label: string; ask: string; hint: string }> = {
  song: {
    label: "Music",
    ask: "Describe the music",
    hint: "Style, mood, instruments. For example: upbeat pop, female vocals, summer",
  },
  sfx: {
    label: "Sound effect",
    ask: "Describe the sound",
    hint: "For example: rain on a tin roof, distant thunder",
  },
};

/**
 * Music from the model the person picks. What the form asks for comes from the model: lyrics only if it
 * sings them, a switch for leaving the singing out only if it can, the lengths it makes. Making music
 * takes a while, and the page says so.
 */
export function MusicWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
}: MusicWorkspaceProps) {
  const { models, runtime, error, loading, reload } = useVoiceModels(api, "music");
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [modeChoice, setModeChoice] = useState<MusicMode | null>(null);
  const [description, setDescription] = useState("");
  const [lyrics, setLyrics] = useState("");
  const [instrumental, setInstrumental] = useState(false);
  const [seconds, setSeconds] = useState<number | null>(null);
  const [seed, setSeed] = useState("");
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [step, setStep] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [made, setMade] = useState(0);
  const abort = useRef<AbortController | null>(null);

  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, "music", modelId);
  const modes = Object.keys(chosen?.music.modes ?? {}) as MusicMode[];
  const mode: MusicMode | null =
    modeChoice && modes.includes(modeChoice) ? modeChoice : (modes[0] ?? null);
  const rules: MusicModeRules | null = (mode && chosen?.music.modes?.[mode]) || null;
  const [lo, usual, hi] = rules?.duration ?? [1, 30, 60];
  const length = Math.max(lo, Math.min(hi, seconds ?? usual));
  const working = step !== null;
  const sings = mode === "song" && rules?.lyrics !== "unused";
  const canSkipSinging = mode === "song" && rules?.instrumental === "toggle";
  const ready = chosen?.state === "ready";

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (!working) return;
    setWaited(0);
    const id = setInterval(() => setWaited((w) => w + 1), 1000);
    return () => clearInterval(id);
  }, [working]);

  async function make() {
    if (!chosen || !mode || working) return;
    setProblem(null);
    setStep("Starting");
    abort.current = new AbortController();
    const options = Object.fromEntries(
      Object.entries(values).filter(
        ([k, v]) => v !== undefined && chosen.options.some((o) => o.name === k),
      ),
    );
    try {
      const r = await makeTrack(
        runs,
        {
          description,
          model: chosen.id,
          mode,
          lyrics: sings && !instrumental ? lyrics : undefined,
          instrumental: canSkipSinging && instrumental,
          duration: length,
          seed: seed.trim() === "" ? undefined : Number(seed),
          options,
        },
        abort.current.signal,
        setStep,
      );
      if (!r.ok) setProblem(r.message);
      else setMade((n) => n + 1);
    } catch (e) {
      if (!abort.current.signal.aborted) {
        setProblem(e instanceof Error ? e.message : "That could not be made.");
      }
    } finally {
      setStep(null);
      void reload();
    }
  }

  if (error) {
    return (
      <p role="alert" className="text-destructive">
        {error}
      </p>
    );
  }
  if (loading) return <Spinner />;

  const speed = chosen?.measured.speed_x;
  return (
    <div className="mx-auto grid w-full min-w-0 max-w-3xl gap-6">
      {runtime ? <RuntimeCard runtime={runtime} api={api} onChanged={reload} /> : null}
      <ModelPicker
        models={models}
        task="music"
        value={chosen?.id ?? null}
        onChange={(id) => {
          setModelId(id);
          setModeChoice(null);
          setSeconds(null);
          setValues({});
          onModelChosen?.(id);
        }}
        onGetModel={onGetModel}
        disabled={working}
      />
      {modes.length > 1 ? (
        <div role="tablist" aria-label="What to make" className="flex gap-2">
          {modes.map((m) => (
            <Button
              key={m}
              role="tab"
              aria-selected={mode === m}
              size="sm"
              variant={mode === m ? "default" : "outline"}
              disabled={working}
              onClick={() => setModeChoice(m)}
            >
              {MODE_TEXT[m].label}
            </Button>
          ))}
        </div>
      ) : null}
      {mode ? (
        <>
          <div className="grid gap-2">
            <Label htmlFor="music-description">{MODE_TEXT[mode].ask}</Label>
            <Textarea
              id="music-description"
              rows={3}
              value={description}
              maxLength={500}
              placeholder={MODE_TEXT[mode].hint}
              disabled={working}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          {sings && !instrumental ? (
            <div className="grid gap-2">
              <Label htmlFor="music-lyrics">
                Lyrics {rules?.lyrics === "required" ? "(needed)" : "(optional)"}
              </Label>
              <Textarea
                id="music-lyrics"
                rows={6}
                value={lyrics}
                maxLength={5000}
                placeholder={"[verse]\nWrite the words here, one line at a time\n[chorus]\n…"}
                disabled={working}
                onChange={(e) => setLyrics(e.target.value)}
              />
            </div>
          ) : null}
          {canSkipSinging ? (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={instrumental}
                disabled={working}
                onChange={(e) => setInstrumental(e.target.checked)}
              />
              No singing (instrumental)
            </label>
          ) : mode === "song" && rules?.instrumental === "always" ? (
            <p className="text-muted-foreground text-sm">This model makes music without singing.</p>
          ) : null}
          <div className="grid gap-2">
            <Label htmlFor="music-length">
              Length
              <span className="ms-auto font-normal text-muted-foreground">{clock(length)}</span>
            </Label>
            <input
              id="music-length"
              type="range"
              min={lo}
              max={hi}
              step={1}
              value={length}
              disabled={working}
              onChange={(e) => setSeconds(Number(e.target.value))}
            />
          </div>
          {chosen ? (
            <OptionFields
              options={chosen.options}
              values={values}
              onChange={(name, v) => setValues((prev) => ({ ...prev, [name]: v }))}
              disabled={working}
            />
          ) : null}
          <div className="grid gap-2">
            <Label htmlFor="music-seed">Seed (optional)</Label>
            <input
              id="music-seed"
              type="number"
              min={0}
              className="h-9 w-40 rounded-md border border-input bg-transparent px-2 text-sm"
              value={seed}
              placeholder="a new one each time"
              disabled={working}
              onChange={(e) => setSeed(e.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              The same seed and words give the same music.
            </p>
          </div>
        </>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={() => void make()}
          disabled={!ready || working || description.trim().length < 3}
        >
          {working ? "Making it…" : "Make"}
        </Button>
        {working ? (
          <>
            <output className="flex items-center gap-2 text-muted-foreground text-sm">
              <Spinner /> {step} · {clock(waited)}
            </output>
            <Button variant="ghost" onClick={() => abort.current?.abort()}>
              Cancel
            </Button>
          </>
        ) : (
          <span className="text-muted-foreground text-sm">
            {speed
              ? `About ${Math.max(1, Math.round(length / speed))} seconds of work on this computer.`
              : "Music takes a while: from under a minute to several, depending on the model and the length."}
          </span>
        )}
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
      <TrackList
        api={api}
        refreshKey={made}
        modelTitle={(id) => models.find((m) => m.id === id)?.title ?? id}
      />
    </div>
  );
}
