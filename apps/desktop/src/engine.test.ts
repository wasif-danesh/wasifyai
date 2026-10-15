import { describe, expect, it } from "vitest";
import { type InstallProgress, humanBytes, installFraction } from "./engine";

const at = (
  index: number,
  done: number | null = null,
  total: number | null = null,
): InstallProgress => ({
  component: "comfyui",
  step: "x",
  label: "x",
  index,
  count: 6,
  bytes_done: done,
  bytes_total: total,
  detail: null,
});

describe("installFraction", () => {
  it("starts at zero and counts finished steps", () => {
    expect(installFraction(at(1))).toBe(0);
    expect(installFraction(at(4))).toBeCloseTo(0.5);
  });

  it("adds the part of the current step that has arrived", () => {
    expect(installFraction(at(2, 5_000_000, 10_000_000))).toBeCloseTo((1 + 0.5) / 6);
  });

  it("never goes past the end or below the start", () => {
    expect(installFraction(at(6, 99, 10))).toBeLessThanOrEqual(1);
    expect(installFraction(at(1, null, 0))).toBe(0);
  });
});

describe("humanBytes", () => {
  it("writes sizes the way the rest of the app does", () => {
    expect(humanBytes(4_294_967_296)).toBe("4.3 GB");
    expect(humanBytes(620_000_000)).toBe("620 MB");
    expect(humanBytes(10)).toBe("1 MB");
  });
});
