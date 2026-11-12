"use client";
// Pointing at a picture in the chat (docs/chat-does-everything-plan.md, CE6): the area a card is about to change, drawn
// on the picture, and a way to draw another; and "Change an area" under a picture the chat made or kept, which asks the
// chat to change only the box the person drew.
import type { ImageSummary, ImagesApi, Region } from "@wasifyai/client";
import { type PointerEvent, useEffect, useRef, useState } from "react";
import { Button } from "../../../components/button";
import { Input } from "../../../components/input";
import { useThreadEnv } from "../env";

const MIN = 0.02; // a box smaller than this share of the picture is a click, not an area

function clamp(v: number): number {
  return Math.min(1, Math.max(0, v));
}

function round(v: number): number {
  return Math.round(v * 1000) / 1000;
}

/** The area in words, for the person and for a screen reader. */
export function regionWords(r: Region): string {
  const pc = (v: number) => `${Math.round(v * 100)}%`;
  return `from ${pc(r.left)} across and ${pc(r.top)} down, ${pc(r.width)} wide and ${pc(r.height)} tall`;
}

function useImage(imageId: string, images: ImagesApi) {
  const [image, setImage] = useState<ImageSummary | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let gone = false;
    images
      .get(imageId)
      .then((i) => !gone && setImage(i))
      .catch(() => !gone && setMissing(true));
    return () => {
      gone = true;
    };
  }, [imageId, images]);
  return { image, missing };
}

/** A library picture with a box on it; dragging across the picture draws a new box. */
export function RegionPicker({
  imageId,
  images,
  region,
  onChange,
  disabled = false,
}: {
  imageId: string;
  images: ImagesApi;
  region: Region | null;
  onChange: (r: Region) => void;
  disabled?: boolean;
}) {
  const { image, missing } = useImage(imageId, images);
  const frame = useRef<HTMLDivElement>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const [drawing, setDrawing] = useState<Region | null>(null);
  if (missing)
    return <p className="text-muted-foreground text-sm">This picture is no longer there.</p>;
  if (!image) return <div className="aspect-square w-48 animate-pulse rounded-lg bg-muted" />;

  const at = (e: PointerEvent) => {
    const box = frame.current?.getBoundingClientRect();
    if (!box || !box.width || !box.height) return null;
    return {
      x: clamp((e.clientX - box.left) / box.width),
      y: clamp((e.clientY - box.top) / box.height),
    };
  };
  const between = (a: { x: number; y: number }, b: { x: number; y: number }): Region => ({
    left: round(Math.min(a.x, b.x)),
    top: round(Math.min(a.y, b.y)),
    width: round(Math.abs(a.x - b.x)),
    height: round(Math.abs(a.y - b.y)),
  });
  const shown = drawing ?? region;
  return (
    <div className="grid w-fit max-w-full gap-1">
      <div
        ref={frame}
        className={`relative w-fit max-w-full touch-none select-none ${disabled ? "" : "cursor-crosshair"}`}
        onPointerDown={(e) => {
          if (disabled) return;
          const p = at(e);
          if (!p) return;
          start.current = p;
          e.currentTarget.setPointerCapture?.(e.pointerId);
          setDrawing({ left: p.x, top: p.y, width: 0, height: 0 });
        }}
        onPointerMove={(e) => {
          const s = start.current;
          const p = s ? at(e) : null;
          if (s && p) setDrawing(between(s, p));
        }}
        onPointerUp={(e) => {
          const s = start.current;
          const p = s ? at(e) : null;
          start.current = null;
          setDrawing(null);
          if (!s || !p) return;
          const r = between(s, p);
          if (r.width >= MIN && r.height >= MIN) onChange(r);
        }}
      >
        <img
          src={image.image_url}
          alt={image.prompt}
          draggable={false}
          width={image.width || undefined}
          height={image.height || undefined}
          className="block h-auto max-h-80 w-auto max-w-full rounded-lg border object-contain"
        />
        {shown ? (
          <div
            data-testid="region-box"
            aria-hidden="true"
            className="pointer-events-none absolute rounded-sm border-2 border-primary bg-primary/20"
            style={{
              left: `${shown.left * 100}%`,
              top: `${shown.top * 100}%`,
              width: `${shown.width * 100}%`,
              height: `${shown.height * 100}%`,
            }}
          />
        ) : null}
      </div>
      <p className="text-muted-foreground text-xs">
        {region ? `The area to change: ${regionWords(region)}.` : "No area yet."}
        {disabled ? "" : " Drag across the picture to draw another."}
      </p>
    </div>
  );
}

/** "Change an area" under a picture: draw a box, say what goes there, and the chat proposes changing only that box. */
export function ChangeArea({ imageId }: { imageId: string }) {
  const { images, onAsk } = useThreadEnv();
  const [open, setOpen] = useState(false);
  const [region, setRegion] = useState<Region | null>(null);
  const [words, setWords] = useState("");
  if (!onAsk) return null;
  if (!open)
    return (
      <div>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(true)}>
          Change an area
        </Button>
      </div>
    );
  const send = () => {
    if (!region || !words.trim()) return;
    onAsk(
      `Change only this area of picture ${imageId} (region left ${region.left}, top ${region.top}, width ${region.width}, height ${region.height}) into: ${words.trim()}`,
    );
    setOpen(false);
    setRegion(null);
    setWords("");
  };
  return (
    <div className="grid max-w-md gap-2 rounded-lg border p-3 text-sm">
      <RegionPicker imageId={imageId} images={images} region={region} onChange={setRegion} />
      <div className="grid gap-1">
        <label htmlFor={`area-words-${imageId}`}>What to put there</label>
        <Input
          id={`area-words-${imageId}`}
          value={words}
          onChange={(e) => setWords(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
          placeholder="a green armchair"
        />
      </div>
      <div className="flex gap-2">
        <Button type="button" size="sm" onClick={send} disabled={!region || !words.trim()}>
          Change it
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
