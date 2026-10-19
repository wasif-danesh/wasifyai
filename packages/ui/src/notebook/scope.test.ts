import type { NotebookFolder, NotebookSource } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import {
  folderTree,
  noReadySourceReason,
  scopeIds,
  scopeLabel,
  sourcesUnder,
  tickOf,
  toggle,
} from "./scope";

const src = (id: string, over: Partial<NotebookSource> = {}): NotebookSource => ({
  id,
  notebook_id: "n",
  folder_id: null,
  title: id,
  kind: "file",
  status: "ready",
  error: null,
  mime: null,
  suffix: null,
  size_bytes: null,
  pages: null,
  created_at: "",
  updated_at: "",
  ...over,
});
const folder = (id: string, parent: string | null = null): NotebookFolder => ({
  id,
  notebook_id: "n",
  parent_id: parent,
  name: id,
});

describe("which sources a question is asked of", () => {
  const folders = [folder("a"), folder("b", "a"), folder("c")];
  const sources = [
    src("1", { folder_id: "a" }),
    src("2", { folder_id: "b" }),
    src("3", { folder_id: "c" }),
    src("4"),
  ];

  it("finds a folder's whole tree", () => {
    expect([...folderTree(folders, "a")].sort()).toEqual(["a", "b"]);
    expect(sourcesUnder(folders, sources, "a").map((s) => s.id)).toEqual(["1", "2"]);
  });

  it("ticks a folder fully, partly or not at all, and toggles whole groups", () => {
    const ids = ["1", "2"];
    expect(tickOf(ids, new Set())).toBe("all");
    expect(tickOf(ids, new Set(["1"]))).toBe("some");
    expect(tickOf(ids, new Set(["1", "2"]))).toBe("none");
    expect(tickOf([], new Set())).toBe("none");
    expect([...toggle(ids, new Set())].sort()).toEqual(["1", "2"]); // ticked: untick all
    expect([...toggle(ids, new Set(["1"]))].sort()).toEqual(["1", "2"]); // mixed: untick all
    expect([...toggle(ids, new Set(["1", "2"]))]).toEqual([]); // none: tick all
  });

  it("sends nothing when nothing is unticked, so a new source counts at once", () => {
    expect(scopeIds(sources, new Set())).toBeUndefined();
    expect(scopeIds(sources, new Set(["gone"]))).toBeUndefined();
    expect(scopeIds(sources, new Set(["3"]))).toEqual(["1", "2", "4"]);
    expect(scopeIds(sources, new Set(["1", "2", "3", "4"]))).toEqual([]);
  });

  it("leaves out sources that are not ready yet", () => {
    const mixed = [src("1"), src("2", { status: "processing" }), src("3", { status: "failed" })];
    expect(scopeIds(mixed, new Set(["1"]))).toEqual([]);
    expect(scopeIds(mixed, new Set(["x", "3"]))).toEqual(["1"]);
  });

  it("says how many are used", () => {
    const list = [src("1"), src("2"), src("3", { status: "pending" })];
    expect(scopeLabel(list, new Set())).toBe("2 sources, 1 being read");
    expect(scopeLabel(list, new Set(["1"]))).toBe("1 of 2 sources, 1 being read");
    expect(scopeLabel([src("1")], new Set())).toBe("1 source");
  });
});

describe("sources that could not be read", () => {
  const failed = (id: string) => ({ ...src(id), status: "failed" as const });
  const reading = (id: string) => ({ ...src(id), status: "processing" as const });

  it("says how many could not be read, and not that they are being read", () => {
    expect(scopeLabel([failed("1"), failed("2"), failed("3")], new Set())).toBe(
      "3 could not be read",
    );
    expect(scopeLabel([src("1"), failed("2")], new Set())).toBe("1 source, 1 could not be read");
    expect(scopeLabel([failed("1"), reading("2")], new Set())).toBe(
      "1 being read, 1 could not be read",
    );
  });

  it("gives the reason no question can be asked yet", () => {
    expect(noReadySourceReason([src("1"), failed("2")])).toBeNull();
    expect(noReadySourceReason([])).toBeNull();
    expect(noReadySourceReason([failed("1"), reading("2")])).toBe(
      "Your sources are still being read.",
    );
    expect(noReadySourceReason([failed("1"), failed("2")])).toMatch(
      /None of your sources could be read/,
    );
  });
});
