"use client";
// The film, playing (ADR-0096 decision 3): HyperFrames' player on the page the engine serves, the
// same page the video is made from. The player is loaded only when this screen opens.
import {
  type ReactNode,
  createElement,
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

export type LivePreviewHandle = {
  play(): void;
  pause(): void;
  seek(seconds: number): void;
};

type PlayerElement = HTMLElement & {
  play?: () => void;
  pause?: () => void;
  seek?: (seconds: number) => void;
  currentTime?: number;
  paused?: boolean;
};

/** Keeps the player out of the first screen's bundle; a test passes its own. */
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
    fallback?: ReactNode;
  }
>(function LivePreview({ url, width, height, at, onTime, onPlaying, load = loadPlayer }, ref) {
  const host = useRef<PlayerElement | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
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
    const playing = () => told.current.onPlaying(true);
    const paused = () => told.current.onPlaying(false);
    const broke = () => setFailed(true);
    player.addEventListener("ready", ready);
    player.addEventListener("timeupdate", time);
    player.addEventListener("play", playing);
    player.addEventListener("pause", paused);
    player.addEventListener("ended", paused);
    player.addEventListener("error", broke);
    return () => {
      player.removeEventListener("ready", ready);
      player.removeEventListener("timeupdate", time);
      player.removeEventListener("play", playing);
      player.removeEventListener("pause", paused);
      player.removeEventListener("ended", paused);
      player.removeEventListener("error", broke);
    };
  }, [loaded]);

  useImperativeHandle(
    ref,
    () => ({
      play: () => host.current?.play?.(),
      pause: () => host.current?.pause?.(),
      seek: (seconds) => host.current?.seek?.(seconds),
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
  return createElement("hyperframes-player", {
    ref: host,
    src: url,
    width,
    height,
    title: "Preview of your video",
    style: {
      display: "block",
      aspectRatio: `${width} / ${height}`,
      maxWidth: "100%",
      maxHeight: "100%",
      width: width >= height ? "100%" : "auto",
      height: width >= height ? "auto" : "100%",
    },
  });
});
