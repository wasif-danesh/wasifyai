"use client";

import {
  type MusicMode,
  type MusicModeRules,
  type MusicRequest,
  type ParsedEvent,
  type Track,
  type VoiceApi,
  makeTrack,
} from "@wasifyai/client";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { EditTrack } from "./EditTrack";
import { LyricsWriter } from "./LyricsWriter";
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
  /** lyrics written elsewhere (the Lyrics screen) */
  initialLyrics?: string | null;
  /** something to do with a track as the screen opens: it was chosen on Your music */
  initialAction?: { kind: "edit" | "again" | "take"; trackId: string } | null;
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
  initialLyrics,
  initialAction,
}: MusicWorkspaceProps) {
  const { models, runtime, error, loading, reload } = useVoiceModels(api, "music");
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [modeChoice, setModeChoice] = useState<MusicMode | null>(null);
  const [description, setDescription] = useState("");
  const [lyrics, setLyrics] = useState(initialLyrics ?? "");
  const [instrumental, setInstrumental] = useState(false);
  const [seconds, setSeconds] = useState<number | null>(null);
  const [seed, setSeed] = useState("");
  const [takes, setTakes] = useState(1);
  const [writing, setWriting] = useState(false);
  const [editing, setEditing] = useState<Track | null>(null);
  const [take, setTake] = useState<[number, number] | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [step, setStep] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [made, setMade] = useState(0);
  const abort = useRef<AbortController | null>(null);

  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, "music", modelId);
  const modes = (Object.keys(chosen?.music.modes ?? {}) as string[]).filter(
    (m): m is MusicMode => m === "song" || m === "sfx",
  ); // "edit" is not something to make: it changes a track (EditTrack)
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
  // an action chosen on Your music runs once, when the models are known
  const acted = useRef(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: once, when the models have loaded
  useEffect(() => {
    if (!initialAction || acted.current || loading) return;
    acted.current = true;
    api
      .track(initialAction.trackId)
      .then((t) => {
        if (initialAction.kind === "edit") setEditing(t);
        else again(t, initialAction.kind === "again");
      })
      .catch(() => setProblem("That piece of music is no longer there."));
  }, [loading]);
  useEffect(() => {
    if (!working) return;
    setWaited(0);
    const id = setInterval(() => setWaited((w) => w + 1), 1000);
    return () => clearInterval(id);
  }, [working]);

  /** Make `count` pieces from one request. With a seed, the takes use that seed and the ones after it;
   * without, each gets its own. */
  async function begin(request: MusicRequest, count: number) {
    setProblem(null);
    setStep("Starting");
    abort.current = new AbortController();
    try {
      for (let i = 0; i < count; i++) {
        setTake([i + 1, count]);
        const seeded =
          request.seed !== undefined ? { ...request, seed: request.seed + i } : request;
        const r = await makeTrack(runs, seeded, abort.current.signal, setStep);
        if (!r.ok) {
          setProblem(r.message);
          break;
        }
        setMade((n) => n + 1);
      }
    } catch (e) {
      if (!abort.current.signal.aborted) {
        setProblem(e instanceof Error ? e.message : "That could not be made.");
      }
    } finally {
      setStep(null);
      setTake(null);
      void reload();
    }
  }

  function make() {
    if (!chosen || !mode || working) return;
    const options = Object.fromEntries(
      Object.entries(values).filter(
        ([k, v]) => v !== undefined && v !== "" && chosen.options.some((o) => o.name === k),
      ),
    );
    void begin(
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
      takes,
    );
  }

  /** Make a piece again from a track's own settings: the same seed gives the same music, a new one
   * another take. The form shows what was used. */
  function again(t: Track, sameSeed: boolean) {
    if (working || (t.mode !== "song" && t.mode !== "sfx")) return;
    const m = models.find((x) => x.id === t.model_id);
    if (!m || m.state !== "ready") {
      setProblem(`${m?.title ?? "That model"} is not ready: get it in Models first.`);
      return;
    }
    setModelId(m.id);
    setModeChoice(t.mode);
    setDescription(t.description);
    setLyrics(t.lyrics);
    setInstrumental(t.instrumental);
    setSeconds(t.seconds);
    setSeed(sameSeed && t.seed !== null ? String(t.seed) : "");
    setValues(t.options);
    setEditing(null);
    void begin(
      {
        description: t.description,
        model: m.id,
        mode: t.mode,
        lyrics: t.lyrics || undefined,
        instrumental: t.instrumental,
        duration: t.seconds,
        seed: sameSeed && t.seed !== null ? t.seed : undefined,
        options: t.options,
      },
      1,
    );
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
              <div className="flex items-center gap-2">
                <Label htmlFor="music-lyrics">
                  Lyrics {rules?.lyrics === "required" ? "(needed)" : "(optional)"}
                </Label>
                <Button
                  size="xs"
                  variant="outline"
                  className="ms-auto"
                  disabled={working}
                  onClick={() => setWriting((w) => !w)}
                >
                  {writing ? "Close the writer" : "Write lyrics for me"}
                </Button>
              </div>
              {writing ? (
                <div className="rounded-lg border p-3">
                  <LyricsWriter
                    runs={runs}
                    style={description || undefined}
                    duration={length}
                    initial={lyrics}
                    onUse={(words) => {
                      setLyrics(words);
                      setWriting(false);
                    }}
                  />
                </div>
              ) : null}
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
              The same seed and words give the same music. With several takes, each uses the next
              seed.
            </p>
          </div>
        </>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={make} disabled={!ready || working || description.trim().length < 3}>
          {working ? "Making it…" : takes > 1 ? `Make ${takes}` : "Make"}
        </Button>
        {!working ? (
          <label className="flex items-center gap-1.5 text-sm">
            Takes
            <select
              className="h-9 rounded-md border border-input bg-transparent px-2"
              value={takes}
              onChange={(e) => setTakes(Number(e.target.value))}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {working ? (
          <>
            <output className="flex items-center gap-2 text-muted-foreground text-sm">
              <Spinner /> {take && take[1] > 1 ? `Take ${take[0]} of ${take[1]}: ` : ""}
              {step} · {clock(waited)}
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
      {editing ? (
        <EditTrack
          api={api}
          runs={runs}
          track={editing}
          models={models}
          onGetModel={onGetModel}
          onDone={() => {
            setEditing(null);
            setMade((n) => n + 1);
          }}
          onClose={() => setEditing(null)}
        />
      ) : null}
      <TrackList
        api={api}
        refreshKey={made}
        modelTitle={(id) => models.find((m) => m.id === id)?.title ?? id}
        onAgain={(t) => again(t, true)}
        onTake={(t) => again(t, false)}
        onEdit={(t) => setEditing(t)}
      />
    </div>
  );
}
