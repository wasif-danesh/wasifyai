// SPDX-License-Identifier: AGPL-3.0-only
import type { Transport } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import { ago, compactCount, createHubApi, paramsLabel } from "./hub";

describe("labels", () => {
  it("counts for a person", () => {
    expect(compactCount(980)).toBe("980");
    expect(compactCount(1_234)).toBe("1.2K");
    expect(compactCount(34_000)).toBe("34K");
    expect(compactCount(1_226_766)).toBe("1.2M");
    expect(compactCount(29_853_801)).toBe("30M");
  });

  it("parameters and age", () => {
    expect(paramsLabel(4_022_468_096)).toBe("4.0B");
    expect(paramsLabel(751_632_384)).toBe("752M");
    expect(paramsLabel(null)).toBe("");
    const now = new Date("2026-10-16T12:00:00Z");
    expect(ago("2026-10-16T01:00:00Z", now)).toBe("today");
    expect(ago("2026-10-14T12:00:00Z", now)).toBe("2 days ago");
    expect(ago("2026-04-16T12:00:00Z", now)).toBe("6 months ago");
    expect(ago(null, now)).toBe("");
  });
});

describe("hub api", () => {
  it("searches with the words, the kind and the sort", async () => {
    const seen: string[] = [];
    const transport: Transport = {
      async fetch(path) {
        seen.push(path);
        return new Response(JSON.stringify({ items: [], stale: false }), { status: 200 });
      },
    };
    await createHubApi(transport).search("qwen 3", "language", "likes");
    expect(seen[0]).toBe("/desktop/hub/search?q=qwen+3&capability=language&sort=likes");
  });

  it("asks to fetch exactly the variant that was shown and only flags memory when chosen", async () => {
    const bodies: string[] = [];
    const transport: Transport = {
      async fetch(_p, init) {
        bodies.push(String(init?.body));
        return new Response(JSON.stringify({ id: "d", status: "running", bytes_total: 5 }), {
          status: 200,
        });
      },
    };
    const api = createHubApi(transport);
    const v = {
      id: "x",
      name: "x",
      quant: "Q4",
      files: ["a.gguf"],
      size: 5,
      sizes: [5],
      fit: null,
    };
    await api.download("acme/demo", v);
    await api.download("acme/demo", v, true);
    expect(JSON.parse(bodies[0] ?? "")).toEqual({ repo: "acme/demo", files: ["a.gguf"], bytes: 5 });
    expect(JSON.parse(bodies[1] ?? "").accept_memory).toBe(true);
  });

  it("says what the engine said when consent is missing", async () => {
    const transport: Transport = {
      fetch: async () =>
        new Response(JSON.stringify({ detail: "Browsing models contacts huggingface.co." }), {
          status: 403,
        }),
    };
    await expect(createHubApi(transport).search("x", "language", "downloads")).rejects.toThrow(
      "huggingface.co",
    );
  });
});
