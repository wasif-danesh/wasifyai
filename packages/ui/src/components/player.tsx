"use client";

import { PauseIcon, PlayIcon } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "./button";
import { Slider } from "./slider";

/** "1:05", "12:40": seconds as a clock. */
function clock(s: number): string {
  const whole = Math.max(0, Math.floor(s));
  const m = Math.floor(whole / 60);
  const sec = whole % 60;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

const PEAKS = new Map<string, number[]>();

/**
 * The shape of a recording as `bars` heights from 0 to 1, read with the browser's audio decoder. Null while it is
 * read, and when it cannot be (no decoder, a file the page may not read): the player then shows its plain bar.
 */
export function useWaveform(src: string | undefined, bars = 96): number[] | null {
  const [peaks, setPeaks] = useState<number[] | null>(() =>
    src ? (PEAKS.get(src) ?? null) : null,
  );
  useEffect(() => {
    if (!src) return setPeaks(null);
    const known = PEAKS.get(src);
    if (known) return setPeaks(known);
    setPeaks(null);
    const Ctx =
      typeof window === "undefined"
        ? undefined
        : (window.AudioContext ??
          (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext);
    if (!Ctx) return;
    let gone = false;
    const ctx = new Ctx();
    fetch(src)
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(String(r.status)))))
      .then((data) => ctx.decodeAudioData(data))
      .then((audio) => {
        const samples = audio.getChannelData(0);
        const size = Math.max(1, Math.floor(samples.length / bars));
        const out: number[] = [];
        for (let i = 0; i < bars; i++) {
          let max = 0;
          for (let j = i * size; j < Math.min(samples.length, (i + 1) * size); j += 16) {
            const v = Math.abs(samples[j] ?? 0);
            if (v > max) max = v;
          }
          out.push(max);
        }
        const top = Math.max(...out, 1e-3);
        const shape = out.map((v) => Math.max(0.06, v / top));
        PEAKS.set(src, shape);
        if (!gone) setPeaks(shape);
      })
      .catch(() => undefined)
      .finally(() => void ctx.close().catch(() => undefined));
    return () => {
      gone = true;
    };
  }, [src, bars]);
  return peaks;
}

/** The waveform as the bar to move through the recording: played part in the strong colour, a slider to assistive tech. */
function Waveform({
  peaks,
  at,
  length,
  title,
  onSeek,
}: {
  peaks: number[];
  at: number;
  length: number;
  title: string;
  onSeek: (seconds: number) => void;
}) {
  const done = length > 0 ? at / length : 0;
  const seekTo = (e: React.PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - box.left) / Math.max(1, box.width)));
    onSeek(f * length);
  };
  return (
    <div
      role="slider"
      tabIndex={0}
      aria-label={`Position in ${title}`}
      aria-valuemin={0}
      aria-valuemax={Math.round(length)}
      aria-valuenow={Math.round(at)}
      aria-valuetext={`${clock(at)} of ${clock(length)}`}
      data-slot="waveform"
      className="flex h-10 min-w-0 flex-1 cursor-pointer items-center gap-px rounded-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      onPointerDown={seekTo}
      onKeyDown={(e) => {
        const step =
          e.key === "ArrowRight" || e.key === "ArrowUp"
            ? 5
            : e.key === "ArrowLeft" || e.key === "ArrowDown"
              ? -5
              : 0;
        if (step) onSeek(Math.min(length, Math.max(0, at + step)));
        else if (e.key === "Home") onSeek(0);
        else if (e.key === "End") onSeek(length);
        else return;
        e.preventDefault();
      }}
    >
      {peaks.map((p, i) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: the bars are a fixed row
          key={i}
          aria-hidden="true"
          className={cn(
            "min-w-px flex-1 rounded-full",
            i / peaks.length < done ? "bg-primary" : "bg-muted-foreground/35",
          )}
          style={{ height: `${Math.round(p * 100)}%` }}
        />
      ))}
    </div>
  );
}

/**
 * The app's own audio player: play and pause, where it is, how long it is, and a bar to move through it, in the
 * app's look in both themes (the browser's player is not). With `waveform`, the bar is the recording's shape.
 */
export function Player({
  src,
  title,
  duration: given,
  autoPlay,
  actions,
  waveform,
  className,
}: {
  src: string;
  /** what is playing, read by assistive tech and shown when given */
  title: string;
  /** seconds, when known before the file is loaded */
  duration?: number;
  autoPlay?: boolean;
  /** anything to put at the end of the bar (a Save button, an `ActionsRow`) */
  actions?: ReactNode;
  /** show the recording's shape as the bar (it is read once per recording) */
  waveform?: boolean;
  className?: string;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const peaks = useWaveform(waveform ? src : undefined);
  const [playing, setPlaying] = useState(false);
  const [at, setAt] = useState(0);
  const [length, setLength] = useState(given ?? 0);
  useEffect(() => {
    setAt(0);
    setPlaying(false);
    setLength(given ?? 0);
  }, [given]);
  const seek = (v: number) => {
    const el = audio.current;
    if (el) el.currentTime = v;
    setAt(v);
  };
  function toggle() {
    const el = audio.current;
    if (!el) return;
    if (el.paused) void el.play()?.catch(() => setPlaying(false));
    else el.pause();
  }
  return (
    <div
      className={cn("flex items-center gap-3 rounded-md border bg-surface px-2 py-1.5", className)}
      data-slot="player"
      data-state={playing ? "playing" : "paused"}
    >
      {/* the element does the work; the controls below are the app's */}
      <audio
        ref={audio}
        src={src}
        preload="metadata"
        autoPlay={autoPlay}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setAt(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          if (Number.isFinite(e.currentTarget.duration)) setLength(e.currentTarget.duration);
        }}
      >
        <track kind="captions" />
      </audio>
      <Button
        type="button"
        size="icon-sm"
        variant={playing ? "secondary" : "default"}
        aria-label={playing ? `Pause ${title}` : `Play ${title}`}
        aria-pressed={playing}
        onClick={toggle}
      >
        {playing ? <PauseIcon aria-hidden="true" /> : <PlayIcon aria-hidden="true" />}
      </Button>
      <span className="min-w-[2.6rem] text-end text-muted-foreground text-xs tabular-nums">
        {clock(at)}
      </span>
      {peaks ? (
        <Waveform peaks={peaks} at={at} length={length} title={title} onSeek={seek} />
      ) : (
        <Slider
          className="min-w-0 flex-1 [&_output]:hidden"
          value={Math.min(at, length || 0)}
          min={0}
          max={length || 1}
          step={0.1}
          label={`Position in ${title}`}
          format={(v) => `${clock(v)} of ${clock(length)}`}
          onValueChange={seek}
        />
      )}
      <span className="min-w-[2.6rem] text-muted-foreground text-xs tabular-nums">
        {clock(length)}
      </span>
      {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
    </div>
  );
}
