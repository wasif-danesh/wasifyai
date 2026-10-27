import { describe, expect, it } from "vitest";
import { minutesText } from "./format";

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
