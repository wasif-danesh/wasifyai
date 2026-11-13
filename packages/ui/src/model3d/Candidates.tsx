"use client";
// "From words": four pictures of what was described, made one after another by the image engine
// (the image engine does one picture at a time), for the person to pick from (ADR-0080 decision 2).
// The cheap steps stay cheap and the long 3D run happens once, on the picture that was chosen.

import { type FlowState, type RunClient, flowReducer, initialState } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { hint } from "../styles";

export type CandidateApi = Pick<RunClient, "startRun">;

const IMAGE_PRODUCT = "wasifyai-image";
/** What the 3D engine takes best, asked for in the words of the picture (ADR-0080, corrected by TD0:
 * "front view at eye level", because a three-quarter view makes the model lean). */
export const WRAPPER =
  "a single object, centred, plain light background, front view at eye level, soft even light";
export const COUNT = 4;

export const wrap = (words: string) => `${words.trim()}, ${WRAPPER}`;

type Slot = FlowState;

export function useCandidates(api: CandidateApi) {
  const [slots, setSlots] = useState<Slot[]>([]);
  const [running, setRunning] = useState(false);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  const start = useCallback(
    async (words: string) => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      setSlots(Array.from({ length: COUNT }, () => initialState));
      setRunning(true);
      const base = Math.floor(Math.random() * 1_000_000);
      for (let i = 0; i < COUNT && !ctrl.signal.aborted; i += 1) {
        const apply = (action: Parameters<typeof flowReducer>[1]) =>
          setSlots((all) => all.map((s, k) => (k === i ? flowReducer(s, action) : s)));
        apply({ type: "submitted" });
        try {
          await api.startRun(
            IMAGE_PRODUCT,
            { mode: "text", prompt: wrap(words), size: "1024x1024", seed: base + i },
            ctrl.signal,
            (event) => apply({ type: "event", event }),
          );
        } catch (e) {
          if (ctrl.signal.aborted) break;
          apply({
            type: "failed",
            message: e instanceof Error && e.message ? e.message : "The picture could not be made.",
          });
        }
      }
      if (!ctrl.signal.aborted) setRunning(false);
    },
    [api],
  );

  const stop = useCallback(() => {
    abort.current?.abort();
    setRunning(false);
  }, []);

  return { slots, running, start, stop };
}

export function Candidates({
  api,
  words,
  busy,
  onPick,
}: {
  api: CandidateApi;
  words: string;
  busy: boolean;
  onPick: (picture: Blob, name: string) => void;
}) {
  const { slots, running, start, stop } = useCandidates(api);
  const [error, setError] = useState<string | null>(null);

  async function pick(url: string, i: number) {
    setError(null);
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("The picture could not be fetched.");
      onPick(await res.blob(), `candidate-${i + 1}.png`);
    } catch {
      setError("That picture could not be used. Try another.");
    }
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <Button
          type="button"
          disabled={!words.trim() || running || busy}
          onClick={() => void start(words)}
        >
          {slots.length === 0 ? "Make 4 pictures" : "Make 4 new pictures"}
        </Button>
        {running ? (
          <Button type="button" variant="ghost" onClick={stop}>
            Stop
          </Button>
        ) : null}
        <span className={hint}>About a minute. You pick the picture before the long step.</span>
      </div>
      {error ? (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      ) : null}
      {slots.length > 0 ? (
        <ul aria-label="Pictures to choose from" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {slots.map((s, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: four fixed places
            <li key={i} className="grid gap-1.5">
              <div
                className={cn(
                  "grid aspect-square place-items-center overflow-hidden rounded-lg border bg-muted",
                )}
              >
                {s.phase === "done" && s.result ? (
                  <img
                    src={s.result.imageUrl}
                    alt={`Choice ${i + 1} of ${COUNT}`}
                    className="size-full object-cover"
                  />
                ) : s.phase === "refused" || s.phase === "error" ? (
                  <p className="p-2 text-center text-sm text-muted-foreground">
                    {s.refusal?.message ?? s.error?.message ?? "That one did not work."}
                  </p>
                ) : s.phase === "idle" ? (
                  <span className={hint}>Waiting</span>
                ) : (
                  <output className={hint}>{s.label || "Making it"}</output>
                )}
              </div>
              {s.phase === "done" && s.result ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void pick(s.result?.imageUrl ?? "", i)}
                >
                  Use this picture
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
