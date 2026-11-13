import { describe, expect, it } from "vitest";
import { minutesText, stepProgress } from "./format";

describe("minutesText", () => {
  it("says one minute for anything up to a minute and a half, in the singular", () => {
    expect(minutesText(2)).toBe("1 minute");
    expect(minutesText(60)).toBe("1 minute");
    expect(minutesText(89)).toBe("1 minute");
  });
  it("rounds longer spans to whole minutes, in the plural", () => {
    expect(minutesText(90)).toBe("2 minutes");
    expect(minutesText(19 * 60 + 20)).toBe("19 minutes");
  });
});

describe("how far a long job is", () => {
  it("reads the chapter and the part of an audiobook, and the line of a dub", () => {
    expect(stepProgress("Chapter 1 of 4, part 1 of 2")).toBe(0);
    expect(stepProgress("Chapter 2 of 4, part 2 of 2")).toBeCloseTo(0.375);
    expect(stepProgress("Chapter 3 of 4")).toBe(0.5);
    expect(stepProgress("Speaking line 4 of 10")).toBeCloseTo(0.3);
    expect(stepProgress("Translating")).toBeUndefined();
    expect(stepProgress(null)).toBeUndefined();
  });
});
