import { describe, expect, it } from "vitest";
import {
  canvasSize,
  coverage,
  invertAlpha,
  rectBetween,
  rectFromShares,
  toMaskPixels,
} from "./mask";

const px = (...alphas: number[]) => alphas.flatMap((a) => [10, 20, 30, a]);

describe("a painted area", () => {
  it("turns shares of the picture into a rectangle, clamped to the picture", () => {
    expect(rectFromShares(200, 100, { left: 0.5, top: 0.5, width: 0.25, height: 0.5 })).toEqual({
      x: 100,
      y: 50,
      w: 50,
      h: 50,
    });
    // reaching past the edge is cut off; nothing left means no rectangle
    expect(rectFromShares(200, 100, { left: 0.9, top: 0, width: 0.5, height: 1 })).toEqual({
      x: 180,
      y: 0,
      w: 20,
      h: 100,
    });
    expect(rectFromShares(200, 100, { left: 1, top: 0, width: 0.5, height: 1 })).toBeNull();
    expect(rectFromShares(200, 100, { left: 0, top: 0, width: 0, height: 1 })).toBeNull();
  });

  it("takes the rectangle between two corners in any order, inside the canvas", () => {
    expect(rectBetween({ x: 30, y: 40 }, { x: 10, y: 5 }, 100, 100)).toEqual({
      x: 10,
      y: 5,
      w: 20,
      h: 35,
    });
    expect(rectBetween({ x: -20, y: -20 }, { x: 500, y: 60 }, 100, 80)).toEqual({
      x: 0,
      y: 0,
      w: 100,
      h: 60,
    });
    expect(rectBetween({ x: 5, y: 5 }, { x: 5, y: 50 }, 100, 100)).toBeNull(); // a line is nothing
  });

  it("measures how much is painted, counting half-painted edge pixels as painted", () => {
    expect(coverage(px(255, 0, 0, 0))).toBe(0.25);
    expect(coverage(px(128, 127))).toBe(0.5);
    expect(coverage([])).toBe(0);
  });

  it("makes the mask the engine reads: white where painted, black elsewhere, opaque", () => {
    const data = px(255, 0, 200, 50);
    toMaskPixels(data);
    expect(data).toEqual([255, 255, 255, 255, 0, 0, 0, 255, 255, 255, 255, 255, 0, 0, 0, 255]);
  });

  it("inverts what is painted", () => {
    const data = px(255, 0, 130, 20);
    invertAlpha(data);
    expect(data.filter((_, i) => i % 4 === 3)).toEqual([0, 255, 0, 255]);
    expect(coverage(data)).toBe(0.5);
  });

  it("sizes the canvas to the picture's shape, no side above the cap", () => {
    expect(canvasSize(4000, 2000)).toEqual({ w: 1024, h: 512 });
    expect(canvasSize(800, 600)).toEqual({ w: 800, h: 600 });
    expect(canvasSize(300, 1200, 600)).toEqual({ w: 150, h: 600 });
  });
});
