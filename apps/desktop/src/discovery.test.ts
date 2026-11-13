// SPDX-License-Identifier: AGPL-3.0-only
import type { Transport } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import { type FoundModel, createDiscoveryApi, detailOf, groupFound } from "./discovery";

const model = (over: Partial<FoundModel>): FoundModel => ({
  id: "a",
  name: "m",
  kind: "language",
  family: "llama",
  format: "gguf",
  quant: "Q4_K_M",
  size: 1,
  path: "/x",
  tool: "ollama",
  tool_title: "Ollama",
  state: "later",
  reason: "",
  use_root: null,
  use: "",
  needs_gb: 0,
  fit: null,
  ...over,
});

describe("groupFound", () => {
  it("groups by what the model is, in a fixed order, and leaves empty groups out", () => {
    const groups = groupFound([
      model({ id: "1", kind: "vae" }),
      model({ id: "2", kind: "video" }),
      model({ id: "3", kind: "language" }),
      model({ id: "4", kind: "text_encoder" }),
    ]);
    expect(groups.map((g) => g.title)).toEqual([
      "Language models",
      "Video models",
      "Parts of image models",
    ]);
    expect(groups[2]?.items.map((i) => i.id)).toEqual(["1", "4"]);
  });
});

describe("detailOf", () => {
  it("joins what is known and skips what is not", () => {
    expect(detailOf(model({}))).toBe("llama · Q4_K_M · GGUF");
    expect(detailOf(model({ family: "", quant: "", format: "repo" }))).toBe("");
  });
});

describe("discovery api", () => {
  it("sends the settings and the id it was given", async () => {
    const calls: { path: string; init?: RequestInit }[] = [];
    const transport: Transport = {
      async fetch(path, init) {
        calls.push({ path, init });
        return new Response(JSON.stringify({ folder: "/models" }), { status: 200 });
      },
    };
    const api = createDiscoveryApi(transport);
    await api.settings(false, ["/a"]);
    expect(calls[0]?.init?.body).toBe('{"enabled":false,"folders":["/a"]}');
    expect(await api.use("abc")).toEqual({ folder: "/models" });
    expect(calls[1]?.path).toBe("/desktop/discovery/use");
  });

  it("says what the engine said when it refuses", async () => {
    const transport: Transport = {
      fetch: async () =>
        new Response(JSON.stringify({ detail: "that file cannot be used in place" }), {
          status: 404,
        }),
    };
    await expect(createDiscoveryApi(transport).use("x")).rejects.toThrow(
      "that file cannot be used in place",
    );
  });
});
