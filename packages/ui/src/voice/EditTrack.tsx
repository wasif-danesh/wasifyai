"use client";

import {
  type EditAction,
  type ParsedEvent,
  type Track,
  type VoiceApi,
  type VoiceModelInfo,
  makeEdit,
} from "@wasifyai/client";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { ModelPicker } from "./ModelPicker";
import { clock, pickModel } from "./format";

const ACTION_TEXT: Record<EditAction, { label: string; hint: string }> = {
  repaint: { label: "Change a part", hint: "Rewrite one stretch of the clip" },
  inpaint: { label: "Change parts", hint: "Rewrite stretches of the clip" },
  extend: { label: "Make it longer", hint: "Carry the music on past its end" },
  cover: { label: "Restyle it", hint: "The same music in another style" },
  restyle: { label: "Restyle it", hint: "The same music in another style" },
};
const USES_RANGES: EditAction[] = ["repaint", "inpaint"];
const USES_STRENGTH: EditAction[] = ["repaint", "cover", "restyle"];

export type EditTrackProps = {
  api: VoiceApi;
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  track: Track;
  /** the music models (only those that can change a clip are offered) */
  models: VoiceModelInfo[];
  onGetModel?: (id: string) => void;
  onDone: (id: string) => void;
  onClose: () => void;
};

/** Change a piece of music that was made: a stretch of it, its length, or its style. The result is a new
 * track; the original stays. What can be done depends on the model. */
export function EditTrack({ runs, track, models, onGetModel, onDone, onClose }: EditTrackProps) {
  const editors = models.filter((m) => m.music.modes?.edit);
  const [modelId, setModelId] = useState<string | null>(null);
  const chosen = editors.find((m) => m.id === modelId) ?? pickModel(editors, "music", modelId);
  const rules = chosen?.music.modes?.edit ?? null;
  const [actionChoice, setActionChoice] = useState<EditAction | null>(null);
  const action: EditAction | null =
    actionChoice && rules?.actions.includes(actionChoice)
      ? actionChoice
      : (rules?.actions[0] ?? null);
  const [description, setDescription] = useState("");
  const [ranges, setRanges] = useState<[number, number][]>([[0, Math.min(10, track.seconds)]]);
  const [strength, setStrength] = useState(0.6);
  const [extend, setExtend] = useState(15);
  const [step, setStep] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  const working = step !== null;
  const needsRanges = action !== null && USES_RANGES.includes(action);
  const ready = chosen?.state === "ready";

  async function apply() {
    if (!chosen || !action || working) return;
    setProblem(null);
    setStep("Starting");
    abort.current = new AbortController();
    try {
      const r = await makeEdit(
        runs,
        {
          source: track.id,
          action,
          description,
          model: chosen.id,
          ...(needsRanges ? { ranges } : {}),
          ...(USES_STRENGTH.includes(action) ? { strength } : {}),
          ...(action === "extend" ? { extend } : {}),
        },
        abort.current.signal,
        setStep,
      );
      if (r.ok) onDone(r.track.id);
      else setProblem(r.message);
    } catch (e) {
      if (!abort.current.signal.aborted) {
        setProblem(e instanceof Error ? e.message : "That could not be changed.");
      }
    } finally {
      setStep(null);
    }
  }

  if (editors.length === 0) {
    return (
      <section aria-label="Change this music" className="grid gap-2 rounded-xl border p-4">
        <p className="text-muted-foreground text-sm">
          None of the music models on this computer can change a clip yet.
        </p>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </section>
    );
  }
  return (
    <section aria-label="Change this music" className="grid gap-4 rounded-xl border bg-card p-4">
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="font-semibold">Change “{track.title}”</h3>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </header>
      <ModelPicker
        models={editors}
        task="music"
        value={chosen?.id ?? null}
        onChange={(id) => {
          setModelId(id);
          setActionChoice(null);
        }}
        onGetModel={onGetModel}
        disabled={working}
      />
      {rules ? (
        <div role="tablist" aria-label="What to do" className="flex flex-wrap gap-2">
          {rules.actions.map((a) => (
            <Button
              key={a}
              role="tab"
              aria-selected={action === a}
              size="sm"
              variant={action === a ? "default" : "outline"}
              title={ACTION_TEXT[a].hint}
              disabled={working}
              onClick={() => setActionChoice(a)}
            >
              {ACTION_TEXT[a].label}
            </Button>
          ))}
        </div>
      ) : null}
      <div className="grid gap-2">
        <Label htmlFor="edit-description">What should it become?</Label>
        <Textarea
          id="edit-description"
          rows={2}
          value={description}
          maxLength={500}
          placeholder="For example: a drum fill and a brighter guitar"
          disabled={working}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      {needsRanges && rules ? (
        <fieldset className="grid gap-2 border-0 p-0">
          <legend className="mb-1 font-medium text-sm">
            Which {ranges.length > 1 ? "parts" : "part"} (seconds, the clip is{" "}
            {clock(track.seconds)})
          </legend>
          {ranges.map((r, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: parts have no identity beyond their order
            <div key={i} className="flex items-center gap-2 text-sm">
              <label className="flex items-center gap-1">
                From
                <input
                  type="number"
                  min={0}
                  max={track.seconds}
                  step={0.5}
                  aria-label={`Part ${i + 1} from`}
                  className="h-9 w-20 rounded-md border border-input bg-transparent px-2"
                  value={r[0]}
                  disabled={working}
                  onChange={(e) =>
                    setRanges((list) =>
                      list.map((x, j) => (j === i ? [Number(e.target.value), x[1]] : x)),
                    )
                  }
                />
              </label>
              <label className="flex items-center gap-1">
                to
                <input
                  type="number"
                  min={0}
                  max={track.seconds}
                  step={0.5}
                  aria-label={`Part ${i + 1} to`}
                  className="h-9 w-20 rounded-md border border-input bg-transparent px-2"
                  value={r[1]}
                  disabled={working}
                  onChange={(e) =>
                    setRanges((list) =>
                      list.map((x, j) => (j === i ? [x[0], Number(e.target.value)] : x)),
                    )
                  }
                />
              </label>
              {ranges.length > 1 ? (
                <Button
                  size="xs"
                  variant="ghost"
                  disabled={working}
                  onClick={() => setRanges((list) => list.filter((_, j) => j !== i))}
                >
                  Remove
                </Button>
              ) : null}
            </div>
          ))}
          {ranges.length < rules.max_ranges ? (
            <Button
              size="xs"
              variant="outline"
              className="justify-self-start"
              disabled={working}
              onClick={() => setRanges((list) => [...list, [0, Math.min(10, track.seconds)]])}
            >
              Add another part
            </Button>
          ) : null}
        </fieldset>
      ) : null}
      {action === "extend" ? (
        <div className="grid gap-2">
          <Label htmlFor="edit-extend">
            Add
            <span className="ms-auto font-normal text-muted-foreground">{extend} s</span>
          </Label>
          <input
            id="edit-extend"
            type="range"
            min={1}
            max={60}
            step={1}
            value={extend}
            disabled={working}
            onChange={(e) => setExtend(Number(e.target.value))}
          />
        </div>
      ) : null}
      {action && USES_STRENGTH.includes(action) ? (
        <div className="grid gap-2">
          <Label htmlFor="edit-strength">
            How much to change
            <span className="ms-auto font-normal text-muted-foreground">{strength.toFixed(2)}</span>
          </Label>
          <input
            id="edit-strength"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={strength}
            disabled={working}
            onChange={(e) => setStrength(Number(e.target.value))}
          />
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={() => void apply()}
          disabled={!ready || working || description.trim().length < 3}
        >
          {working ? "Changing it…" : "Change it"}
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
      </div>
      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : null}
    </section>
  );
}
