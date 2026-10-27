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

/**
 * The app's own audio player: play and pause, where it is, how long it is, and a bar to move through it, in the
 * app's look in both themes (the browser's player is not). The waveform comes in a later stage.
 */
export function Player({
  src,
  title,
  duration: given,
  autoPlay,
  actions,
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
  className?: string;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [at, setAt] = useState(0);
  const [length, setLength] = useState(given ?? 0);
  useEffect(() => {
    setAt(0);
    setPlaying(false);
    setLength(given ?? 0);
  }, [given]);
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
      <Slider
        className="min-w-0 flex-1 [&_output]:hidden"
        value={Math.min(at, length || 0)}
        min={0}
        max={length || 1}
        step={0.1}
        label={`Position in ${title}`}
        format={(v) => `${clock(v)} of ${clock(length)}`}
        onValueChange={(v) => {
          const el = audio.current;
          if (el) el.currentTime = v;
          setAt(v);
        }}
      />
      <span className="min-w-[2.6rem] text-muted-foreground text-xs tabular-nums">
        {clock(length)}
      </span>
      {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
    </div>
  );
}
