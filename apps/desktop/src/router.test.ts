// SPDX-License-Identifier: AGPL-3.0-only
import { describe, expect, it } from "vitest";
import { chatPath, parseConversation, parseHash, routePath } from "./router";

describe("router", () => {
  it("reads every route back from its own path", () => {
    for (const r of ["home", "create", "edit", "library", "models", "settings"] as const) {
      expect(parseHash(`#${routePath(r)}`)).toBe(r);
    }
  });

  it("treats an empty or unknown hash as home", () => {
    expect(parseHash("")).toBe("home");
    expect(parseHash("#")).toBe("home");
    expect(parseHash("#/nowhere")).toBe("home");
  });

  it("ignores a query string", () => {
    expect(parseHash("#/images/create?x=1")).toBe("create");
  });

  it("opens a saved conversation from its own path and reads the home screen from it", () => {
    expect(parseConversation("#/chat/3f2a-91bc")).toBe("3f2a-91bc");
    expect(parseConversation("#/chat/../etc")).toBeNull();
    expect(parseConversation("#/")).toBeNull();
    expect(parseConversation(`#${chatPath("abc")}`)).toBe("abc");
    expect(chatPath(null)).toBe("/");
    expect(parseHash("#/chat/abc")).toBe("home");
  });
});
