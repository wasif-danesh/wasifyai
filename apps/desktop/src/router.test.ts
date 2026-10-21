// SPDX-License-Identifier: AGPL-3.0-only
import { describe, expect, it } from "vitest";
import {
  NEW_NOTEBOOK,
  chatPath,
  notebookPath,
  parseConversation,
  parseHash,
  parseNotebook,
  routePath,
  visit,
} from "./router";

describe("router", () => {
  it("reads every route back from its own path", () => {
    for (const r of [
      "home",
      "create",
      "edit",
      "library",
      "models",
      "settings",
      "notebooks",
      "speak",
      "transcribe",
      "voices",
      "music",
      "tracks",
      "lyrics",
      "separate",
      "convert",
      "speechedit",
      "lipsync",
      "dub",
      "audiobook",
      "video",
      "animate",
      "extend",
      "videos",
    ] as const) {
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

  it("opens a notebook, or a draft, from its own path", () => {
    expect(parseNotebook("#/notebooks/9f3c-12ab")).toBe("9f3c-12ab");
    expect(parseNotebook(`#${notebookPath(NEW_NOTEBOOK)}`)).toBe("new");
    expect(parseNotebook("#/notebooks")).toBeNull();
    expect(parseNotebook("#/notebooks/../x")).toBeNull();
    expect(parseHash("#/notebooks/9f3c")).toBe("notebook");
    expect(parseHash("#/notebooks")).toBe("notebooks");
    expect(notebookPath(null)).toBe("/notebooks");
  });
});

describe("the back and forward arrows", () => {
  const walk = (...hashes: string[]) =>
    hashes.reduce((v, h) => visit(v, h), { list: ["#/"], at: 0 });

  it("count the screens visited, and step back and forward through them", () => {
    let v = walk("#/images/create", "#/video/create");
    expect(v).toEqual({ list: ["#/", "#/images/create", "#/video/create"], at: 2 });
    v = visit(v, "#/images/create"); // back
    expect(v.at).toBe(1);
    v = visit(v, "#/video/create"); // forward
    expect(v.at).toBe(2);
    v = visit(visit(v, "#/images/create"), "#/models"); // somewhere new drops what was ahead
    expect(v).toEqual({ list: ["#/", "#/images/create", "#/models"], at: 2 });
  });

  it("do not count the same screen twice", () => {
    expect(walk("#/models", "#/models").list).toEqual(["#/", "#/models"]);
  });
});
