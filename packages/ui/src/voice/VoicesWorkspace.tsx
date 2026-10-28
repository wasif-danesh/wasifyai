"use client";

import {
  type ConsentBasis,
  type ParsedEvent,
  type SavedVoice,
  type VoiceApi,
  makeSpeech,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { clock } from "./format";

export const CONSENT_TEXT: Record<ConsentBasis, string> = {
  own: "This is my own voice.",
  permission: "I have the permission of the person whose voice this is.",
};

const EXAMPLES = [
  "A deep, calm older man with a slow British accent",
  "A bright, energetic young woman who speaks quickly",
  "A warm, gentle narrator with a soft voice",
];
/** The line a voice says when the person asks to hear it. */
export const SAMPLE = "Hello, this is how I sound. I hope you like it.";

export type VoicesWorkspaceProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  /** open Text to speech with this voice chosen */
  onUseVoice?: (id: string) => void;
};

/**
 * Voices of your own: described in words, or cloned from a short recording. A voice is not tied to
 * one model: it is spoken by any model that can do that (Text to speech lists them). A cloned voice
 * asks whose voice it is, and keeps the answer.
 */
export function VoicesWorkspace({ api, runs, onUseVoice }: VoicesWorkspaceProps) {
  const [voices, setVoices] = useState<SavedVoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<"design" | "clone">("design");
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [said, setSaid] = useState("");
  const [consent, setConsent] = useState<ConsentBasis | null>(null);
  const [trying, setTrying] = useState<string | null>(null);
  const [heard, setHeard] = useState<Record<string, string>>({});
  const abort = useRef<AbortController | null>(null);

  const load = useCallback(
    () =>
      api
        .voices()
        .then(setVoices)
        .catch((e) =>
          setProblem(e instanceof Error ? e.message : "The voices could not be listed."),
        )
        .finally(() => setLoading(false)),
    [api],
  );
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => () => abort.current?.abort(), []);

  async function save() {
    setProblem(null);
    setSaving(true);
    try {
      if (mode === "design") {
        await api.designVoice(name.trim(), description.trim());
      } else if (file && consent) {
        await api.cloneVoice(file, name.trim(), consent, said.trim() || undefined);
      }
      setName("");
      setDescription("");
      setFile(null);
      setSaid("");
      setConsent(null);
      await load();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That voice could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function tryVoice(v: SavedVoice) {
    setProblem(null);
    setTrying(v.id);
    abort.current = new AbortController();
    try {
      const r = await makeSpeech(runs, { text: SAMPLE, savedVoice: v.id }, abort.current.signal);
      if (r.ok) setHeard((h) => ({ ...h, [v.id]: r.speech.audio_url }));
      else setProblem(r.message);
    } catch (e) {
      if (!abort.current.signal.aborted) {
        setProblem(e instanceof Error ? e.message : "That could not be made.");
      }
    } finally {
      setTrying(null);
    }
  }

  async function remove(id: string) {
    await api.removeVoice(id);
    setVoices((list) => list.filter((v) => v.id !== id));
  }

  async function editWords(v: SavedVoice) {
    const next = window.prompt("The words spoken in the recording", v.reference_text);
    if (next === null) return;
    try {
      const saved = await api.updateVoice(v.id, { reference_text: next });
      setVoices((list) => list.map((x) => (x.id === v.id ? saved : x)));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be saved.");
    }
  }

  const ready =
    name.trim().length > 0 &&
    (mode === "design" ? description.trim().length >= 3 : file !== null && consent !== null);

  return (
    <div className="mx-auto grid w-full min-w-0 max-w-3xl gap-6">
      <section
        aria-label="New voice"
        className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 rounded-2xl border bg-card p-5"
      >
        <div role="tablist" aria-label="How to make the voice" className="flex flex-wrap gap-2">
          {(
            [
              ["design", "Describe a voice"],
              ["clone", "Clone from a recording"],
            ] as const
          ).map(([id, label]) => (
            <Button
              key={id}
              role="tab"
              aria-selected={mode === id}
              variant={mode === id ? "default" : "outline"}
              size="sm"
              onClick={() => setMode(id)}
            >
              {label}
            </Button>
          ))}
        </div>
        <div className="grid gap-2">
          <Label htmlFor="voice-name">Name</Label>
          <input
            id="voice-name"
            className="h-10 rounded-md border border-input bg-transparent px-3 text-sm"
            value={name}
            maxLength={100}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        {mode === "design" ? (
          <div className="grid gap-2">
            <Label htmlFor="voice-description">Describe the voice</Label>
            <Textarea
              id="voice-description"
              rows={3}
              value={description}
              maxLength={300}
              placeholder="Age, pace, accent, energy. Change one thing at a time to hear what helps."
              onChange={(e) => setDescription(e.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((x) => (
                <Button
                  key={x}
                  size="xs"
                  variant="outline"
                  className="h-auto max-w-full whitespace-normal py-1 text-start"
                  onClick={() => setDescription(x)}
                >
                  {x}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <div className="grid gap-2">
              <Label htmlFor="voice-file">A recording of the voice (3 to 30 seconds)</Label>
              <input
                id="voice-file"
                type="file"
                accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="voice-said">What is said in the recording</Label>
              <Textarea
                id="voice-said"
                rows={2}
                value={said}
                maxLength={1000}
                placeholder="Some models need these words to copy the voice well"
                onChange={(e) => setSaid(e.target.value)}
              />
            </div>
            <fieldset className="grid gap-2 border-0 p-0">
              <legend className="mb-1 font-medium text-sm">Whose voice is it?</legend>
              {(Object.keys(CONSENT_TEXT) as ConsentBasis[]).map((b) => (
                <label key={b} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="consent"
                    checked={consent === b}
                    onChange={() => setConsent(b)}
                  />
                  {CONSENT_TEXT[b]}
                </label>
              ))}
            </fieldset>
          </>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void save()} disabled={!ready || saving}>
            {saving ? "Saving…" : "Save voice"}
          </Button>
        </div>
      </section>
      {problem ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}
      {loading ? (
        <Spinner />
      ) : voices.length === 0 ? (
        <p className="text-muted-foreground">No voices of your own yet.</p>
      ) : (
        <section aria-label="Your voices" className="grid gap-3">
          <h2 className="font-semibold">Your voices</h2>
          <ul className="grid gap-3">
            {voices.map((v) => (
              <li key={v.id} className="grid gap-2 rounded-xl border bg-card p-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-medium">{v.name}</span>
                  <span className="text-muted-foreground text-xs">
                    {v.kind === "design"
                      ? "described"
                      : `cloned, ${clock(v.reference_seconds ?? 0)}`}
                  </span>
                </div>
                {v.kind === "design" ? (
                  <p className="text-muted-foreground text-sm">{v.description}</p>
                ) : (
                  <>
                    {v.reference_url ? (
                      // biome-ignore lint/a11y/useMediaCaption: a short recording of a voice
                      <audio controls preload="none" src={v.reference_url} className="h-9 w-full" />
                    ) : null}
                    <p className="text-muted-foreground text-sm">
                      {v.reference_text || "No words added for this recording."}{" "}
                      <button
                        type="button"
                        className="underline underline-offset-4"
                        onClick={() => void editWords(v)}
                      >
                        Change the words
                      </button>
                    </p>
                    {v.consent.statement ? (
                      <p className="text-muted-foreground text-xs">{v.consent.statement}</p>
                    ) : null}
                  </>
                )}
                {heard[v.id] ? (
                  // biome-ignore lint/a11y/useMediaCaption: the sample line is shown on the page
                  <audio
                    controls
                    src={heard[v.id]}
                    className="h-9 w-full"
                    aria-label={`${v.name} speaking`}
                  />
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={trying !== null}
                    onClick={() => void tryVoice(v)}
                  >
                    {trying === v.id ? "Making a sample…" : "Hear a sample"}
                  </Button>
                  {onUseVoice ? (
                    <Button size="sm" variant="outline" onClick={() => onUseVoice(v.id)}>
                      Use in Text to speech
                    </Button>
                  ) : null}
                  <Button size="sm" variant="ghost" onClick={() => void remove(v.id)}>
                    Delete
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
