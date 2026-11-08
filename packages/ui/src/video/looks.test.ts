import type { TrainedModel } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import { looksFor, looksOf } from "./Looks";

const model = (over: Record<string, unknown>, card: Record<string, unknown>) =>
  ({
    id: "m",
    name: "Ena",
    trigger_word: "enaz",
    card: { ...card },
    ...over,
  }) as unknown as TrainedModel;

describe("looksOf", () => {
  it("lists only video models that are published to the video engine", () => {
    const list = looksOf([
      model(
        {},
        { family: "video", published: { lora_name: "wasify-video-ena-12345678.safetensors" } },
      ),
      model({ name: "Not yet" }, { family: "video", published: null }),
      model({ name: "A picture one" }, { published: { lora_name: "pic.safetensors" } }),
    ]);
    expect(list).toEqual([
      {
        name: "wasify-video-ena-12345678.safetensors",
        title: "Ena",
        word: "enaz",
        model: "ltx-video-2b",
      },
    ]);
  });

  it("knows the video model each look was taught on, and offers a look only with that model", () => {
    const list = looksOf([
      model(
        { base: "ltx-video-2b" },
        { family: "video", published: { lora_name: "a.safetensors" } },
      ),
      model({ base: "ltx-2.5" }, { family: "video", published: { lora_name: "b.safetensors" } }),
    ]);
    expect(list.map((l) => l.model)).toEqual(["ltx-video-2b", "ltx-2.5"]);
    expect(looksFor(list, "ltx-2.5").map((l) => l.name)).toEqual(["b.safetensors"]);
    expect(looksFor(list, "wan2.2-14b")).toEqual([]);
    expect(looksFor(list, null)).toHaveLength(2); // the engine checks when no model is chosen
  });
});
