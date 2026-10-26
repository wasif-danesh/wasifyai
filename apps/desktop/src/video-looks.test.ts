// SPDX-License-Identifier: AGPL-3.0-only
import type { TrainedModel } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import { looksOf } from "./video-looks";

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
      { name: "wasify-video-ena-12345678.safetensors", title: "Ena", word: "enaz" },
    ]);
  });
});
