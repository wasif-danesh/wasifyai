// SPDX-License-Identifier: AGPL-3.0-only
import { describe, expect, it } from "vitest";
import { greeting } from "./pages/Home";

describe("greeting", () => {
  it("follows the hour", () => {
    expect(greeting(3)).toBe("Good night");
    expect(greeting(9)).toBe("Good morning");
    expect(greeting(14)).toBe("Good afternoon");
    expect(greeting(20)).toBe("Good evening");
  });
});
