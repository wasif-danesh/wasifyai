// SPDX-License-Identifier: AGPL-3.0-only
import type { Transport } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import { contextLabel, createLanguageApi } from "./language";

describe("contextLabel", () => {
  it("is short for a person", () => {
    expect(contextLabel(2048)).toBe("2K");
    expect(contextLabel(32768)).toBe("32K");
    expect(contextLabel(512)).toBe("512");
  });
});

describe("language api", () => {
  it("sends the choice as it is and reads the engine's own refusal", async () => {
    const calls: { path: string; init?: RequestInit }[] = [];
    const transport: Transport = {
      async fetch(path, init) {
        calls.push({ path, init });
        if (init?.body && String(init.body).includes("huge")) {
          return new Response(JSON.stringify({ detail: "It will not run here." }), { status: 409 });
        }
        return new Response(JSON.stringify({ selected: null }), { status: 200 });
      },
    };
    const api = createLanguageApi(transport);
    await api.choose({ item_id: "abc", context: 8192 });
    expect(calls[0]?.init?.method).toBe("PUT");
    expect(calls[0]?.init?.body).toBe('{"item_id":"abc","context":8192}');
    await expect(api.choose({ item_id: "huge", context: 8192 })).rejects.toThrow(
      "It will not run here.",
    );
  });
});
