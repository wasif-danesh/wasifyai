"use client";
// The film, playing (ADR-0096 decision 3): HyperFrames' player on the page the engine serves, the
// same page the video is made from. The player is loaded only when this screen opens.
import type { PlacedPart } from "@wasifyai/client";
import {
  type ReactNode,
  createElement,
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { MeasuredPart } from "./ArrangeOverlay";

export type LivePreviewHandle = {
  play(): void;
  pause(): void;
  seek(seconds: number): void;
  /** Where a scene's parts are on the picture now, as the page reports it; null if it does not answer. */
  measure(scene: string): Promise<Record<string, MeasuredPart> | null>;
  /** Move a part on the page while it is dragged. The document says where it really is. */
  place(scene: string, part: string, rect: PlacedPart): void;
};

const MEASURE_WAIT_MS = 800;

type PlayerElement = HTMLElement & {
  play?: () => void;
  pause?: () => void;
  seek?: (seconds: number) => void;
  currentTime?: number;
  paused?: boolean;
};

/** The page inside the player; its frame is in the player's open shadow root. */
const frameOf = (player: PlayerElement | null) =>
  player?.shadowRoot?.querySelector("iframe")?.contentWindow ?? null;

/** Keeps the player out of the first screen's bundle; a test passes its own. */
const SEEK_AFTER_LOAD_MS = [300, 700, 1200, 2000, 3500];

const loadPlayer = () => import("./vendor/hyperframes-player.global.js");

export const LivePreview = forwardRef<
  LivePreviewHandle,
  {
    /** The page's address; a new one reloads the player. */
    url: string | null;
    width: number;
    height: number;
    /** Where to be after loading: the film stays where it was when the page changes. */
    at: number;
    onTime: (seconds: number) => void;
    onPlaying: (playing: boolean) => void;
    load?: () => Promise<unknown>;
    /** Drawn over the film, in the film's own box (arranging on it). */
    over?: ReactNode;
  }
>(function LivePreview(
  { url, width, height, at, onTime, onPlaying, load = loadPlayer, over },
  ref,
) {
  const host = useRef<PlayerElement | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const atNow = useRef(at);
  atNow.current = at;
  const told = useRef({ onTime, onPlaying });
  told.current = { onTime, onPlaying };

  useEffect(() => {
    let gone = false;
    load()
      .then(() => {
        if (!gone) setLoaded(true);
      })
      .catch(() => {
        if (!gone) setFailed(true);
      });
    return () => {
      gone = true;
    };
  }, [load]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: the element exists only once it has loaded
  useEffect(() => {
    const player = host.current;
    if (!player) return;
    const ready = () => player.seek?.(atNow.current);
    const time = () => told.current.onTime(Number(player.currentTime) || 0);
    const started = () => {
      setIsPlaying(true);
      told.current.onPlaying(true);
    };
    const paused = () => {
      setIsPlaying(false);
      told.current.onPlaying(false);
    };
    const broke = () => setFailed(true);
    player.addEventListener("ready", ready);
    player.addEventListener("timeupdate", time);
    player.addEventListener("play", started);
    player.addEventListener("pause", paused);
    player.addEventListener("ended", paused);
    player.addEventListener("error", broke);
    return () => {
      player.removeEventListener("ready", ready);
      player.removeEventListener("timeupdate", time);
      player.removeEventListener("play", started);
      player.removeEventListener("pause", paused);
      player.removeEventListener("ended", paused);
      player.removeEventListener("error", broke);
    };
  }, [loaded]);

  // a new page starts at 0:00, and it takes the player a moment to reach it: the film stays where
  // it was. Asked a few times, because the player has no event for a page it loads again.
  const playing = useRef(false);
  playing.current = isPlaying;
  useEffect(() => {
    if (!url) return;
    const timers = SEEK_AFTER_LOAD_MS.map((ms) =>
      setTimeout(() => {
        if (!playing.current) host.current?.seek?.(atNow.current);
      }, ms),
    );
    return () => {
      for (const timer of timers) clearTimeout(timer);
    };
  }, [url]);

  useImperativeHandle(
    ref,
    () => ({
      play: () => host.current?.play?.(),
      pause: () => host.current?.pause?.(),
      seek: (seconds) => host.current?.seek?.(seconds),
      measure: (scene) =>
        new Promise((resolve) => {
          const page = frameOf(host.current);
          if (!page) {
            resolve(null);
            return;
          }
          const done = (found: Record<string, MeasuredPart> | null) => {
            removeEventListener("message", answer);
            clearTimeout(late);
            resolve(found);
          };
          const answer = (e: MessageEvent) => {
            if (e.source !== page || e.data?.type !== "wasify-parts") return;
            if (e.data.scene === scene) done(e.data.parts);
          };
          const late = setTimeout(() => done(null), MEASURE_WAIT_MS);
          addEventListener("message", answer);
          page.postMessage({ type: "wasify-measure", scene }, "*");
        }),
      place: (scene, part, rect) => {
        frameOf(host.current)?.postMessage({ type: "wasify-place", scene, part, rect }, "*");
      },
    }),
    [],
  );

  if (failed) {
    return (
      <p className="m-0 max-w-sm p-4 text-center text-muted-foreground text-sm" role="alert">
        The preview could not be shown here. Your video can still be made.
      </p>
    );
  }
  if (!loaded || !url) {
    return <output className="text-muted-foreground text-sm">Opening the preview…</output>;
  }
  return (
    <div
      className="relative"
      style={{
        aspectRatio: `${width} / ${height}`,
        maxWidth: "100%",
        maxHeight: "100%",
        width: width >= height ? "100%" : "auto",
        height: width >= height ? "auto" : "100%",
      }}
    >
      {createElement("hyperframes-player", {
        ref: host,
        src: url,
        width,
        height,
        title: "Preview of your video",
        style: { display: "block", width: "100%", height: "100%" },
      })}
      {over}
    </div>
  );
});
