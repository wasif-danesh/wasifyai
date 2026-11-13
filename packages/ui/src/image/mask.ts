// The arithmetic of a painted area (Inpaint): kept free of the canvas so it is tested without one.

/** A rectangle in pixels of the canvas. */
export type Rect = { x: number; y: number; w: number; h: number };

/** A rectangle given as shares (0 to 1) of the picture's width and height, clamped to the picture. */
export function rectFromShares(
  width: number,
  height: number,
  s: { left: number; top: number; width: number; height: number },
): Rect | null {
  const x0 = Math.round(Math.min(1, Math.max(0, s.left)) * width);
  const y0 = Math.round(Math.min(1, Math.max(0, s.top)) * height);
  const x1 = Math.round(Math.min(1, Math.max(0, s.left + s.width)) * width);
  const y1 = Math.round(Math.min(1, Math.max(0, s.top + s.height)) * height);
  return x1 > x0 && y1 > y0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
}

/** The rectangle between two corners, in any order, kept inside the canvas. */
export function rectBetween(
  a: { x: number; y: number },
  b: { x: number; y: number },
  width: number,
  height: number,
): Rect | null {
  const x0 = Math.round(Math.min(width, Math.max(0, Math.min(a.x, b.x))));
  const y0 = Math.round(Math.min(height, Math.max(0, Math.min(a.y, b.y))));
  const x1 = Math.round(Math.min(width, Math.max(0, Math.max(a.x, b.x))));
  const y1 = Math.round(Math.min(height, Math.max(0, Math.max(a.y, b.y))));
  return x1 > x0 && y1 > y0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
}

/** A pixel counts as painted above this alpha (antialiased edges are half painted). */
export const PAINTED_ALPHA = 128;

/** The share (0 to 1) of pixels that are painted, from canvas RGBA data. */
export function coverage(rgba: ArrayLike<number>): number {
  const pixels = Math.floor(rgba.length / 4);
  if (pixels === 0) return 0;
  let painted = 0;
  for (let i = 3; i < rgba.length; i += 4) if ((rgba[i] ?? 0) >= PAINTED_ALPHA) painted++;
  return painted / pixels;
}

/**
 * Canvas RGBA data turned, in place, into the mask the engine reads: white where painted, black
 * elsewhere, fully opaque. The colour the person saw does not matter, only where it was.
 */
export function toMaskPixels(rgba: Uint8ClampedArray | number[]): void {
  for (let i = 0; i < rgba.length; i += 4) {
    const v = (rgba[i + 3] ?? 0) >= PAINTED_ALPHA ? 255 : 0;
    rgba[i] = v;
    rgba[i + 1] = v;
    rgba[i + 2] = v;
    rgba[i + 3] = 255;
  }
}

/** Paint ↔ not painted, in place: what was painted is cleared and the rest is painted (alpha only). */
export function invertAlpha(rgba: Uint8ClampedArray | number[]): void {
  for (let i = 3; i < rgba.length; i += 4) rgba[i] = (rgba[i] ?? 0) >= PAINTED_ALPHA ? 0 : 255;
}

/** The canvas size for a picture: its own shape, no side longer than `max`. */
export function canvasSize(width: number, height: number, max = 1024): { w: number; h: number } {
  const scale = Math.min(1, max / Math.max(width, height, 1));
  return { w: Math.max(1, Math.round(width * scale)), h: Math.max(1, Math.round(height * scale)) };
}
