"use client";
// Arranging on the preview (ADR-0096 MX4): over the film, a box for each part of the scene. Drag one to
// move it, a corner to make it bigger, or choose it and use the arrow keys. A drag moves the page as it
// goes; what stays is the document, when the drag ends.
import type { PlacedPart } from "@wasifyai/client";
import { useRef, useState } from "react";
import { cn } from "../../cn";

/** Where a part is on the picture now, in percent, as the page reports it. */
export type MeasuredPart = { x: number; y: number; w: number; h: number };

const NAMES: Record<string, string> = {
  bar: "line above the title",
  title: "title",
  subtitle: "line under the title",
  mark: "quote mark",
  quote: "quote",
  author: "who said it",
  rows: "numbers",
  strap: "name strap",
  captions: "captions",
  caption: "captions along the bottom",
};
const SAFE_PERCENT = 6; // the word check's margin (templates.SAFE): 6% of the width, on every side
const STEP = 1;
const BIG_STEP = 5;
const MIN_WIDTH = 3;
const MIN_SCALE = 0.4;
const MAX_SCALE = 3;
const SCALE_STEP = 0.05;

const round = (n: number) => Math.round(n * 100) / 100;
const clamp = (n: number, low: number, high: number) => Math.max(low, Math.min(high, n));

/** Where a part is, as it can be placed: its place in the document, or where the page measured it. */
export function placeOf(measured: MeasuredPart, placed?: PlacedPart): PlacedPart {
  return placed ?? { x: round(measured.x), y: round(measured.y), w: round(measured.w), scale: 1 };
}

/** Moved by so much, staying on the picture. */
export function moved(from: PlacedPart, height: number, dx: number, dy: number): PlacedPart {
  return {
    ...from,
    x: round(clamp(from.x + dx, 0, 100 - from.w)),
    y: round(clamp(from.y + dy, 0, Math.max(0, 100 - height))),
  };
}

/** Made wider by so much: the letters grow with the box, as with a picture. */
export function resized(from: PlacedPart, dw: number): PlacedPart {
  const w = clamp(from.w + dw, MIN_WIDTH, 100 - from.x);
  const scale = clamp((from.scale * w) / from.w, MIN_SCALE, MAX_SCALE);
  return {
    ...from,
    w: round((from.w * scale) / from.scale),
    scale: Math.round(scale * 1000) / 1000,
  };
}

export function ArrangeOverlay({
  parts,
  placed,
  ratio,
  onLive,
  onCommit,
}: {
  /** the picture's width over its height: the word check's margin is the same distance on every side */
  ratio: number;
  /** what the page reports for this scene (nothing until it has answered) */
  parts: Record<string, MeasuredPart> | null;
  placed: Record<string, PlacedPart>;
  /** a drag is under way: move the page */
  onLive: (part: string, rect: PlacedPart) => void;
  /** one finished move; moves with the same `together` are one Undo step */
  onCommit: (part: string, rect: PlacedPart, together?: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const tall = SAFE_PERCENT * ratio;
  const [dragging, setDragging] = useState<{ part: string; rect: PlacedPart } | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);

  function start(
    e: React.PointerEvent,
    part: string,
    measured: MeasuredPart,
    how: "move" | "size",
  ) {
    const area = box.current?.getBoundingClientRect();
    if (!area) return;
    e.preventDefault();
    e.stopPropagation();
    setChosen(part);
    const from = placeOf(measured, placed[part]);
    const x0 = e.clientX;
    const y0 = e.clientY;
    let rect = from;
    const follow = (m: PointerEvent) => {
      const dx = ((m.clientX - x0) / area.width) * 100;
      const dy = ((m.clientY - y0) / area.height) * 100;
      rect = how === "move" ? moved(from, measured.h, dx, dy) : resized(from, dx);
      setDragging({ part, rect });
      onLive(part, rect);
    };
    const end = () => {
      window.removeEventListener("pointermove", follow);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      setDragging(null);
      if (rect !== from) onCommit(part, rect);
    };
    window.addEventListener("pointermove", follow);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  }

  function key(e: React.KeyboardEvent, part: string, measured: MeasuredPart) {
    const step = e.shiftKey ? BIG_STEP : STEP;
    const from = placeOf(measured, placed[part]);
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, -step],
      ArrowDown: [0, step],
    };
    const by = moves[e.key];
    let rect: PlacedPart | null = by ? moved(from, measured.h, by[0], by[1]) : null;
    if (e.key === "+" || e.key === "=") rect = resized(from, from.w * SCALE_STEP);
    if (e.key === "-") rect = resized(from, -from.w * SCALE_STEP);
    if (!rect) return;
    e.preventDefault();
    onLive(part, rect);
    onCommit(part, rect, `arrange:${part}`);
  }

  return (
    <div ref={box} className="absolute inset-0" data-slot="arrange">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute border border-white/40 border-dashed"
        style={{
          left: `${SAFE_PERCENT}%`,
          right: `${SAFE_PERCENT}%`,
          top: `${tall}%`,
          bottom: `${tall}%`,
        }}
      />
      {Object.entries(parts ?? {}).map(([part, measured]) => {
        if (measured.h <= 0 || measured.w <= 0) return null;
        const now = dragging?.part === part ? dragging.rect : placed[part];
        const scaleBy = now && placed[part] ? now.scale / placed[part].scale : 1;
        const left = now?.x ?? measured.x;
        const top = now?.y ?? measured.y;
        const width = now && dragging?.part === part ? now.w : measured.w;
        const height = dragging?.part === part ? measured.h * scaleBy : measured.h;
        const outside =
          left < SAFE_PERCENT - 0.5 ||
          left + width > 100 - SAFE_PERCENT + 0.5 ||
          top < tall - 0.5 ||
          top + height > 100 - tall + 0.5;
        return (
          <button
            key={part}
            type="button"
            aria-label={`Move the ${NAMES[part] ?? part}. Arrow keys move it, plus and minus resize it.${outside ? " It is too close to the edge for a video to be made." : ""}`}
            aria-pressed={chosen === part}
            onFocus={() => setChosen(part)}
            onPointerDown={(e) => start(e, part, measured, "move")}
            onKeyDown={(e) => key(e, part, measured)}
            className={cn(
              "absolute cursor-move touch-none rounded-sm border border-white/70 border-dashed bg-transparent p-0",
              chosen === part && "border-2 border-primary border-solid",
              outside && "border-2 border-destructive border-solid",
            )}
            style={{
              left: `${left}%`,
              top: `${top}%`,
              width: `${width}%`,
              height: `${height}%`,
            }}
          >
            <span
              aria-hidden="true"
              onPointerDown={(e) => start(e, part, measured, "size")}
              className="absolute -right-1.5 -bottom-1.5 size-3 cursor-nwse-resize touch-none rounded-[2px] border-2 border-primary bg-white"
            />
          </button>
        );
      })}
    </div>
  );
}

/** A layout: the scene's words moved together, so each part is still an ordinary part to move. */
export function laidOut(
  where: "top" | "middle" | "bottom",
  parts: Record<string, MeasuredPart>,
  placed: Record<string, PlacedPart>,
): Record<string, PlacedPart> {
  const group = Object.entries(parts).filter(([part, m]) => part !== "caption" && m.h > 0);
  if (group.length === 0) return placed;
  const top = Math.min(...group.map(([, m]) => m.y));
  const bottom = Math.max(...group.map(([, m]) => m.y + m.h));
  const dy =
    where === "top" ? 10 - top : where === "bottom" ? 90 - bottom : 50 - (top + bottom) / 2;
  const out = { ...placed };
  for (const [part, m] of group) {
    const from = placeOf(m, placed[part]);
    out[part] = { ...from, x: round(m.x), y: round(m.y + dy), w: from.w };
  }
  return out;
}
