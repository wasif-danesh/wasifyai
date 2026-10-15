// SPDX-License-Identifier: AGPL-3.0-only
import { describe, expect, it } from "vitest";
import { sizeName, when } from "./images";
import { greeting } from "./pages/Home";

describe("images helpers", () => {
  it("names the common shapes", () => {
    expect(sizeName(1024, 1024)).toBe("Square 1:1");
    expect(sizeName(1024, 768)).toBe("Landscape 4:3");
    expect(sizeName(768, 1024)).toBe("Portrait 3:4");
    expect(sizeName(1344, 756)).toBe("Wide 16:9");
    expect(sizeName(756, 1344)).toBe("Tall 9:16");
    expect(sizeName(1000, 300)).toBe("1000×300");
  });

  it("says today and yesterday in words", () => {
    const now = new Date("2026-10-15T15:00:00");
    expect(when("2026-10-15T08:00:00", now)).toBe("Today");
    expect(when("2026-10-14T20:00:00", now)).toBe("Yesterday");
  });
});

describe("greeting", () => {
  it("follows the hour", () => {
    expect(greeting(3)).toBe("Good night");
    expect(greeting(9)).toBe("Good morning");
    expect(greeting(14)).toBe("Good afternoon");
    expect(greeting(20)).toBe("Good evening");
  });
});
