"use client";

import {
  type Ref,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import {
  canvasSize,
  coverage,
  invertAlpha,
  rectBetween,
  rectFromShares,
  toMaskPixels,
} from "./mask";

type Tool = "brush" | "eraser" | "rectangle";

/** What the screen asks of the painter when the person presses Create. */
export type MaskPainterHandle = {
  /** The painted area as a black and white PNG of the picture's shape, or null when nothing is painted. */
  exportMask(): Promise<File | null>;
};

const UNDO_STEPS = 8;
const NUMBERS = [
  ["left", "From the left"],
  ["top", "From the top"],
  ["width", "Width"],
  ["height", "Height"],
] as const;

/**
 * Paint the part of a picture to change (Inpaint). Brush, eraser and rectangle with the pointer; the same
 * rectangle by numbers for the keyboard. The paint is kept at the picture's own shape; what leaves is a
 * mask, white where painted. Presentational: the screen uploads the mask when the person presses Create.
 */
export function MaskPainter({
  picture,
  disabled = false,
  onCoverage,
  handleRef,
}: {
  picture: { previewUrl: string; width: number; height: number };
  disabled?: boolean;
  /** The share of the picture that is painted, 0 to 1, after every change. */
  onCoverage?: (share: number) => void;
  handleRef?: Ref<MaskPainterHandle>;
}) {
  const id = useId();
  const canvas = useRef<HTMLCanvasElement>(null);
  const tint = useRef<HTMLSpanElement>(null);
  const history = useRef<ImageData[]>([]);
  const drag = useRef<{ from: { x: number; y: number }; base: ImageData | null } | null>(null);
  const { w, h } = canvasSize(picture.width, picture.height);
  const [tool, setTool] = useState<Tool>("brush");
  const [size, setSize] = useState(8); // percent of the longer side
  const [share, setShare] = useState(0);
  const [numbers, setNumbers] = useState({ left: 25, top: 25, width: 30, height: 30 });

  const context = useCallback(
    () => canvas.current?.getContext("2d", { willReadFrequently: true }),
    [],
  );

  const report = useCallback(() => {
    const ctx = context();
    const next = ctx ? coverage(ctx.getImageData(0, 0, w, h).data) : 0;
    setShare(next);
    onCoverage?.(next);
  }, [context, w, h, onCoverage]);

  // a new picture starts with nothing painted
  // biome-ignore lint/correctness/useExhaustiveDependencies: the picture is the trigger
  useEffect(() => {
    history.current = [];
    context()?.clearRect(0, 0, w, h);
    report();
  }, [picture.previewUrl]);

  const remember = useCallback(() => {
    const ctx = context();
    if (!ctx) return;
    history.current.push(ctx.getImageData(0, 0, w, h));
    if (history.current.length > UNDO_STEPS) history.current.shift();
  }, [context, w, h]);

  /** The theme's colour, read from a styled element: the screen never names a colour itself. */
  const paint = useCallback((ctx: CanvasRenderingContext2D) => {
    const colour = tint.current ? getComputedStyle(tint.current).color : "";
    if (colour) ctx.fillStyle = colour;
    if (colour) ctx.strokeStyle = colour;
  }, []);

  const at = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return {
      x: ((e.clientX - box.left) / Math.max(1, box.width)) * w,
      y: ((e.clientY - box.top) / Math.max(1, box.height)) * h,
    };
  };

  const dab = (
    ctx: CanvasRenderingContext2D,
    from: { x: number; y: number },
    to: { x: number; y: number },
  ) => {
    ctx.save();
    paint(ctx);
    ctx.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = Math.max(2, (size / 100) * Math.max(w, h));
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x + 0.01, to.y); // a click without a drag still leaves a dot
    ctx.stroke();
    ctx.restore();
  };

  const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const ctx = context();
    if (disabled || !ctx) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    remember();
    const p = at(e);
    if (tool === "rectangle") {
      drag.current = { from: p, base: ctx.getImageData(0, 0, w, h) };
    } else {
      drag.current = { from: p, base: null };
      dab(ctx, p, p);
    }
  };

  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const ctx = context();
    const d = drag.current;
    if (!ctx || !d) return;
    const p = at(e);
    if (tool === "rectangle") {
      if (d.base) ctx.putImageData(d.base, 0, 0);
      const r = rectBetween(d.from, p, w, h);
      if (r) {
        ctx.save();
        paint(ctx);
        ctx.fillRect(r.x, r.y, r.w, r.h);
        ctx.restore();
      }
    } else {
      dab(ctx, d.from, p);
      d.from = p;
    }
  };

  const up = () => {
    if (!drag.current) return;
    drag.current = null;
    report();
  };

  function addRectangle() {
    const ctx = context();
    const r = rectFromShares(w, h, {
      left: numbers.left / 100,
      top: numbers.top / 100,
      width: numbers.width / 100,
      height: numbers.height / 100,
    });
    if (!ctx || !r) return;
    remember();
    ctx.save();
    paint(ctx);
    ctx.fillRect(r.x, r.y, r.w, r.h);
    ctx.restore();
    report();
  }

  function undo() {
    const ctx = context();
    const last = history.current.pop();
    if (!ctx || !last) return;
    ctx.putImageData(last, 0, 0);
    report();
  }

  function clear() {
    const ctx = context();
    if (!ctx) return;
    remember();
    ctx.clearRect(0, 0, w, h);
    report();
  }

  function invert() {
    const ctx = context();
    if (!ctx) return;
    remember();
    const data = ctx.getImageData(0, 0, w, h);
    invertAlpha(data.data);
    // the new paint is the theme's colour too, whatever the old paint was
    ctx.putImageData(data, 0, 0);
    ctx.save();
    paint(ctx);
    ctx.globalCompositeOperation = "source-in";
    ctx.fillRect(0, 0, w, h);
    ctx.restore();
    report();
  }

  useImperativeHandle(
    handleRef,
    () => ({
      async exportMask() {
        const ctx = context();
        if (!ctx) return null;
        const data = ctx.getImageData(0, 0, w, h);
        if (coverage(data.data) === 0) return null;
        toMaskPixels(data.data);
        const out = document.createElement("canvas");
        out.width = w;
        out.height = h;
        out.getContext("2d")?.putImageData(data, 0, 0);
        const blob = await new Promise<Blob | null>((resolve) => out.toBlob(resolve, "image/png"));
        return blob ? new File([blob], "mask.png", { type: "image/png" }) : null;
      },
    }),
    [context, w, h],
  );

  const percent = Math.round(share * 100);

  return (
    <div className="grid gap-3">
      <div
        className="relative w-full max-w-[28rem] overflow-hidden rounded-lg border"
        style={{ aspectRatio: `${w} / ${h}` }}
      >
        <img
          src={picture.previewUrl}
          alt="The original, before the change"
          className="absolute inset-0 size-full object-fill"
          draggable={false}
        />
        <canvas
          ref={canvas}
          width={w}
          height={h}
          role="img"
          aria-label="The painted area. Paint on it with a mouse or a finger, or choose a rectangle by numbers below."
          className={cn(
            "absolute inset-0 size-full touch-none opacity-60",
            disabled
              ? "cursor-not-allowed"
              : tool === "rectangle"
                ? "cursor-crosshair"
                : "cursor-cell",
          )}
          onPointerDown={down}
          onPointerMove={move}
          onPointerUp={up}
          onPointerCancel={up}
        />
        <span
          ref={tint}
          className="pointer-events-none absolute size-0 text-primary"
          aria-hidden="true"
        />
      </div>

      <fieldset className="m-0 flex flex-wrap items-center gap-2 border-0 p-0">
        <legend className="sr-only">Painting tools</legend>
        <Chip aria-pressed={tool === "brush"} onClick={() => setTool("brush")}>
          Brush
        </Chip>
        <Chip aria-pressed={tool === "eraser"} onClick={() => setTool("eraser")}>
          Eraser
        </Chip>
        <Chip aria-pressed={tool === "rectangle"} onClick={() => setTool("rectangle")}>
          Rectangle
        </Chip>
        <label
          className="flex items-center gap-2 text-muted-foreground text-sm"
          htmlFor={`${id}-size`}
        >
          Size
          <input
            id={`${id}-size`}
            type="range"
            min={1}
            max={30}
            value={size}
            disabled={tool === "rectangle"}
            onChange={(e) => setSize(Number(e.target.value))}
          />
        </label>
      </fieldset>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="outline" onClick={undo} disabled={disabled}>
          Undo
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={clear}
          disabled={disabled || share === 0}
        >
          Clear
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={invert} disabled={disabled}>
          Invert
        </Button>
        <output className="text-muted-foreground text-sm">
          {share === 0
            ? "Nothing painted yet."
            : `${percent < 1 ? "Under 1" : percent}% of the picture is painted.`}
        </output>
      </div>

      <details className="rounded-lg border px-3 py-2">
        <summary className="cursor-pointer text-sm">Choose a rectangle by numbers</summary>
        <div className="mt-3 grid grid-cols-2 gap-3">
          {NUMBERS.map(([key, label]) => (
            <label key={key} className="grid gap-1 text-muted-foreground text-sm">
              {label} (%)
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={numbers[key]}
                className="rounded-md border bg-transparent px-2 py-1 text-foreground"
                onChange={(e) =>
                  setNumbers((n) => ({
                    ...n,
                    [key]: Math.min(100, Math.max(0, Number(e.target.value))),
                  }))
                }
              />
            </label>
          ))}
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-3"
          onClick={addRectangle}
          disabled={disabled}
        >
          Paint this rectangle
        </Button>
      </details>
    </div>
  );
}
