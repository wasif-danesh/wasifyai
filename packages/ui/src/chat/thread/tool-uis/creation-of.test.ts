import { describe, expect, it } from "vitest";
import { creationOf } from "./ActionCards";

describe("creationOf", () => {
  it("finds what a result made by its id key, its kind and id, or its address", () => {
    expect(creationOf({ image_id: "i1" })).toEqual(["image", "i1"]);
    expect(creationOf({ kind: "track", id: "t1" })).toEqual(["track", "t1"]);
    // lip sync says `clip_id`, and its address says it is a lipsync
    expect(
      creationOf({ clip_id: "c1", uri: "wasify://creation/lipsync/d68611be39cc4f22" }),
    ).toEqual(["lipsync", "d68611be39cc4f22"]);
    expect(creationOf({ uri: "https://example.com/creation/x/y" })).toBeNull();
    expect(creationOf({ message: "Done." })).toBeNull();
  });
});
