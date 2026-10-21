"use client";

import {
  type AddedPicture,
  type AudioSource,
  type Clip,
  type LipSyncEngine,
  type ParsedEvent,
  type PictureBasis,
  type Speech,
  type Track,
  type VoiceApi,
  type VoiceBasis,
  makeClip,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Bar } from "../components/progress-bar";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { useChoicesFor } from "../models";
import { formatBytes } from "../notebook/format";
import { fileNameFor, useSaveCopy } from "../save";
import { ModelPicker } from "./ModelPicker";
import { clock, pickModel } from "./format";
import { useVoiceModels } from "./use-voice-models";

export const PICTURE_TEXT: Record<PictureBasis, string> = {
  drawn: "This picture is a drawing, painting or other artwork, not a photograph of a person.",
  own: "This is a picture of me.",
  permission: "This is a picture of someone who has given me permission to use it.",
};

export const VOICE_TEXT: Record<VoiceBasis, string> = {
  generated: "The voice was made on this computer from words (text to speech).",
  own: "This is my own voice.",
  permission: "The person whose voice this is has given me permission to use it.",
};

export const MARK = "AI-generated";

export type LipSyncWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  onGetModel?: (id: string) => void;
  initialModel?: string | null;
  onModelChosen?: (id: string) => void;
};

/** Setting up the lip sync engine: a program environment of about 2 GB, fetched only on a click
 * after the size is shown. The model's own files (4.2 GB) are in Models. */
function EngineCard({
  engine,
  api,
  onChanged,
}: {
  engine: LipSyncEngine;
  api: VoiceApi;
  onChanged: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // in the app window the model's own dialog sets the engine up with it (ADR-0086)
  const inDialog = useChoicesFor("faces") !== null;
  if (engine.installed) return null;
  const { plan, install } = engine;
  if (inDialog && plan.supported) return null;
  const working = install.state === "installing";
  async function go() {
    setAsking(false);
    setProblem(null);
    try {
      await api.installLipsyncEngine(plan.bytes);
      onChanged();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That did not work.");
    }
  }
  return (
    <section aria-label="Set up lip sync" className="grid gap-3 rounded-2xl border bg-card p-5">
      <h2 className="font-semibold text-lg">Set up lip sync on this computer</h2>
      {!plan.supported ? (
        <p className="text-muted-foreground">
          There is no lip sync engine for this kind of computer yet.
        </p>
      ) : (
        <>
          <p className="text-muted-foreground">
            Lip sync runs here, with no account and nothing sent away. It needs MuseTalk's program
            and its environment ({formatBytes(plan.bytes)}); the model's files are fetched in Models
            afterwards. Setting up takes a few minutes.
          </p>
          {working ? (
            <div className="grid gap-2">
              <Bar
                value={install.total_bytes ? install.done_bytes / install.total_bytes : undefined}
              />
              <output className="text-muted-foreground text-sm">{install.message}</output>
            </div>
          ) : asking ? (
            <div className="flex flex-wrap items-center gap-2">
              <span>Download about {formatBytes(plan.bytes)} now?</span>
              <Button onClick={() => void go()}>Download</Button>
              <Button variant="ghost" onClick={() => setAsking(false)}>
                Not now
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button disabled={!plan.uv} onClick={() => setAsking(true)}>
                Set up lip sync ({formatBytes(plan.bytes)})
              </Button>
              {!plan.uv ? (
                <span className="text-muted-foreground text-sm">
                  The installer tool is missing: repair the app first.
                </span>
              ) : null}
            </div>
          )}
        </>
      )}
      {install.state === "failed" ? (
        <p role="alert" className="text-destructive text-sm">
          {install.message}
        </p>
      ) : null}
      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : null}
    </section>
  );
}

type Library = { tracks: Track[]; speeches: Speech[] };

/**
 * Talking videos: a picture and a voice make a video of the face saying it. The model is chosen from a
 * list (ADR-0066). The person says what the picture is and whose voice it is before anything is made;
 * that answer is kept with the video, and every video carries a visible "AI-generated" mark that
 * cannot be turned off (ADR-0044).
 */
export function LipSyncWorkspace({
  api,
  runs,
  onGetModel,
  initialModel,
  onModelChosen,
}: LipSyncWorkspaceProps) {
  const { models, error, loading, reload } = useVoiceModels(api, "lipsync");
  const [engine, setEngine] = useState<LipSyncEngine | null>(null);
  const [modelId, setModelId] = useState<string | null>(initialModel ?? null);
  const [picture, setPicture] = useState<AddedPicture | null>(null);
  const [pictureBasis, setPictureBasis] = useState<PictureBasis | null>(null);
  const [voiceFrom, setVoiceFrom] = useState<"words" | "recording">("words");
  const [words, setWords] = useState("");
  const [source, setSource] = useState<AudioSource | null>(null);
  const [voiceBasis, setVoiceBasis] = useState<VoiceBasis | null>(null);
  const [library, setLibrary] = useState<Library>({ tracks: [], speeches: [] });
  const [clips, setClips] = useState<Clip[]>([]);
  const [step, setStep] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const pictureInput = useRef<HTMLInputElement>(null);
  const recordingInput = useRef<HTMLInputElement>(null);

  const chosen = models.find((m) => m.id === modelId) ?? pickModel(models, "lipsync", modelId);
  const working = step !== null;
  const ready = chosen?.state === "ready";
  const maxWords = 1000;

  const loadEngine = useCallback(
    () =>
      api
        .lipsyncEngine()
        .then(setEngine)
        .catch(() => undefined),
    [api],
  );
  const loadClips = useCallback(
    () =>
      api
        .clips()
        .then(setClips)
        .catch(() => undefined),
    [api],
  );
  useEffect(() => {
    void loadEngine();
    void loadClips();
    Promise.all([api.tracks({ limit: 200 }), api.speeches(200)])
      .then(([tracks, speeches]) => setLibrary({ tracks, speeches }))
      .catch(() => undefined);
  }, [api, loadEngine, loadClips]);
  useEffect(() => () => abort.current?.abort(), []);
  const installing = engine?.install.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const id = setInterval(() => {
      void loadEngine();
      void reload();
    }, 1000);
    return () => clearInterval(id);
  }, [installing, loadEngine, reload]);
  useEffect(() => {
    if (!working) return;
    setWaited(0);
    const id = setInterval(() => setWaited((w) => w + 1), 1000);
    return () => clearInterval(id);
  }, [working]);

  // words are always made here; a recording is only "made here" when it is a speech from the library
  const voiceChoices: VoiceBasis[] =
    voiceFrom === "words"
      ? ["generated"]
      : source?.kind === "speech"
        ? ["generated", "own", "permission"]
        : ["own", "permission"];
  const basis = voiceFrom === "words" ? "generated" : voiceBasis;
  const basisOk = basis !== null && voiceChoices.includes(basis);
  const voiceReady = voiceFrom === "words" ? words.trim().length >= 2 : source !== null;
  const canMake = ready && picture !== null && pictureBasis !== null && basisOk && voiceReady;

  async function addPicture(file: File) {
    setProblem(null);
    try {
      setPicture(await api.addPicture(file));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That picture could not be added.");
    }
  }

  async function addRecording(file: File) {
    setProblem(null);
    try {
      const t = await api.importTrack(file);
      setLibrary((l) => ({ ...l, tracks: [t, ...l.tracks] }));
      setSource({ kind: "track", id: t.id });
      setVoiceBasis(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That recording could not be added.");
    }
  }

  async function make() {
    if (!chosen || !picture || !pictureBasis || !basis || working) return;
    setProblem(null);
    setStep("Starting");
    abort.current = new AbortController();
    const signal = abort.current.signal;
    try {
      const r = await makeClip(
        runs,
        {
          picture: picture.id,
          pictureBasis,
          voiceBasis: basis,
          model: chosen.id,
          ...(voiceFrom === "words" ? { text: words } : { source: source ?? undefined }),
        },
        signal,
        setStep,
      );
      if (r.ok) {
        setPicture(null);
        setPictureBasis(null);
        setWords("");
        await loadClips();
      } else {
        setProblem(r.message);
      }
    } catch (e) {
      if (!signal.aborted) setProblem(e instanceof Error ? e.message : "That could not be made.");
    } finally {
      setStep(null);
      void reload();
    }
  }

  const saveCopy = useSaveCopy();
  async function save(c: Clip) {
    setProblem(null);
    try {
      await saveCopy({
        name: fileNameFor(c.title, "mp4", "video"),
        blob: () => api.downloadClip(c.id),
      });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be saved.");
    }
  }

  async function rename(c: Clip) {
    const next = window.prompt("Name this video", c.title)?.trim();
    if (!next || next === c.title) return;
    const saved = await api.updateClip(c.id, { title: next });
    setClips((list) => list.map((x) => (x.id === saved.id ? saved : x)));
  }

  async function remove(id: string) {
    await api.removeClip(id);
    setClips((list) => list.filter((x) => x.id !== id));
  }

  if (error) {
    return (
      <p role="alert" className="text-destructive">
        {error}
      </p>
    );
  }
  if (loading || engine === null) return <Spinner />;

  const speed = chosen?.measured.speed_x;
  const voiceSeconds =
    voiceFrom === "recording" && source
      ? source.kind === "track"
        ? library.tracks.find((t) => t.id === source.id)?.seconds
        : library.speeches.find((s) => s.id === source.id)?.seconds
      : Math.max(2, words.trim().split(/\s+/).length / 2.5);
  return (
    <div className="mx-auto grid w-full min-w-0 max-w-3xl gap-6">
      <EngineCard engine={engine} api={api} onChanged={loadEngine} />
      <ModelPicker
        models={models}
        task="lipsync"
        value={chosen?.id ?? null}
        onChange={(id) => {
          setModelId(id);
          onModelChosen?.(id);
        }}
        onGetModel={onGetModel}
        disabled={working}
      />

      <fieldset className="grid gap-3" disabled={working}>
        <legend className="font-medium">1. The picture</legend>
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={pictureInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="sr-only"
            aria-label="Choose a picture"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void addPicture(f);
            }}
          />
          <Button variant="outline" onClick={() => pictureInput.current?.click()}>
            {picture ? "Choose another picture" : "Choose a picture"}
          </Button>
          <span className="text-muted-foreground text-sm">
            A front-facing face works best. Photos are cleaned of location and camera data.
          </span>
        </div>
        {picture ? (
          <img
            src={picture.url}
            alt="The face to bring to life"
            className="max-h-64 w-fit rounded-lg border object-contain"
          />
        ) : null}
        <div role="radiogroup" aria-label="What the picture is" className="grid gap-1.5">
          {(Object.keys(PICTURE_TEXT) as PictureBasis[]).map((b) => (
            <label key={b} className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="picture-basis"
                checked={pictureBasis === b}
                onChange={() => setPictureBasis(b)}
                className="mt-1"
              />
              {PICTURE_TEXT[b]}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="grid gap-3" disabled={working}>
        <legend className="font-medium">2. The voice</legend>
        <div role="tablist" aria-label="Where the voice comes from" className="flex gap-2">
          {(["words", "recording"] as const).map((v) => (
            <Button
              key={v}
              role="tab"
              aria-selected={voiceFrom === v}
              size="sm"
              variant={voiceFrom === v ? "default" : "outline"}
              onClick={() => {
                setVoiceFrom(v);
                setVoiceBasis(null);
              }}
            >
              {v === "words" ? "Words to say" : "A recording"}
            </Button>
          ))}
        </div>
        {voiceFrom === "words" ? (
          <div className="grid gap-2">
            <Label htmlFor="lipsync-words">What should it say?</Label>
            <Textarea
              id="lipsync-words"
              rows={3}
              maxLength={maxWords}
              value={words}
              placeholder="Good evening, and welcome."
              onChange={(e) => setWords(e.target.value)}
            />
          </div>
        ) : (
          <div className="grid gap-2">
            <Label htmlFor="lipsync-recording">Which recording?</Label>
            <div className="flex flex-wrap items-center gap-2">
              <select
                id="lipsync-recording"
                className="h-10 min-w-0 flex-1 rounded-md border border-input bg-transparent px-3 text-sm"
                value={source ? `${source.kind}:${source.id}` : ""}
                onChange={(e) => {
                  const [kind, ...id] = e.target.value.split(":");
                  setSource(
                    kind === "track" || kind === "speech" ? { kind, id: id.join(":") } : null,
                  );
                  setVoiceBasis(null);
                }}
              >
                <option value="">Choose…</option>
                {library.tracks.length > 0 ? (
                  <optgroup label="Your music and recordings">
                    {library.tracks.map((t) => (
                      <option key={t.id} value={`track:${t.id}`}>
                        {t.title} ({clock(t.seconds)})
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {library.speeches.length > 0 ? (
                  <optgroup label="Speech you made">
                    {library.speeches.map((s) => (
                      <option key={s.id} value={`speech:${s.id}`}>
                        {s.text.slice(0, 50)} ({clock(s.seconds)})
                      </option>
                    ))}
                  </optgroup>
                ) : null}
              </select>
              <input
                ref={recordingInput}
                type="file"
                accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.caf,.aiff"
                className="sr-only"
                aria-label="Add a recording from this computer"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) void addRecording(f);
                }}
              />
              <Button variant="outline" onClick={() => recordingInput.current?.click()}>
                Add a recording
              </Button>
            </div>
          </div>
        )}
        <div role="radiogroup" aria-label="Whose voice it is" className="grid gap-1.5">
          {voiceFrom === "words" ? (
            <p className="text-sm">{VOICE_TEXT.generated}</p>
          ) : (
            voiceChoices.map((b) => (
              <label key={b} className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="voice-basis"
                  checked={voiceBasis === b}
                  onChange={() => setVoiceBasis(b)}
                  className="mt-1"
                />
                {VOICE_TEXT[b]}
              </label>
            ))
          )}
        </div>
      </fieldset>

      <p className="rounded-lg border bg-muted/40 p-3 text-sm">
        Every video is marked "{MARK}" in the corner and in its file. The mark cannot be turned off.
        Your answers above are kept with the video.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => void make()} disabled={!canMake || working}>
          {working ? "Making the video…" : "Make the video"}
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
        ) : speed && voiceSeconds ? (
          <span className="text-muted-foreground text-sm">
            About {Math.max(1, Math.round(voiceSeconds / speed / 60))} minutes of work on this
            computer for {clock(voiceSeconds)} of video.
          </span>
        ) : null}
        {!ready && chosen ? (
          <span className="text-muted-foreground text-sm">
            Set lip sync up and get the model first (see above).
          </span>
        ) : null}
      </div>
      {problem ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}

      <section aria-label="Your videos" className="grid gap-3">
        <h2 className="font-semibold">Your videos</h2>
        {clips.length === 0 ? <p className="text-muted-foreground">Nothing made yet.</p> : null}
        <ul className="grid gap-4">
          {clips.map((c) => (
            <li key={c.id} className="grid gap-2 rounded-xl border bg-card p-3">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-medium">{c.title}</span>
                <span className="text-muted-foreground text-xs">
                  {clock(c.seconds)} · {c.width}×{c.height}
                </span>
              </div>
              {/* biome-ignore lint/a11y/useMediaCaption: a talking video made from the person's own words or recording */}
              <video
                controls
                preload="metadata"
                poster={c.picture_url}
                src={c.video_url}
                className="max-h-80 w-fit max-w-full rounded-lg"
              />
              <p className="text-muted-foreground text-xs">
                {c.consent.picture ? PICTURE_TEXT[c.consent.picture] : ""}{" "}
                {c.consent.voice ? VOICE_TEXT[c.consent.voice] : ""}
              </p>
              <div className="flex flex-wrap gap-1">
                <Button size="sm" variant="ghost" onClick={() => void save(c)}>
                  Save MP4
                </Button>
                <Button size="sm" variant="ghost" onClick={() => void rename(c)}>
                  Rename
                </Button>
                <Button size="sm" variant="ghost" onClick={() => void remove(c.id)}>
                  Delete
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
