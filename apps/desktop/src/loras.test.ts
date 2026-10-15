// SPDX-License-Identifier: AGPL-3.0-only
import { HttpError, type Transport } from "@wasifyai/client";
import { describe, expect, it } from "vitest";
import { createLorasApi } from "./loras";

describe("lorasApi", () => {
  it("lists the styles that are ready and the ones one click away", async () => {
    const paths: string[] = [];
    const transport: Transport = {
      fetch: async (path) => {
        paths.push(path);
        return new Response(
          JSON.stringify({ ready: [{ name: "ink.safetensors" }], available: [] }),
        );
      },
    };
    const list = await createLorasApi(transport).list();
    expect(paths).toEqual(["/desktop/loras"]);
    expect(list.ready).toHaveLength(1);
    expect(list.available).toEqual([]);
  });

  it("fails with the status when the engine refuses", async () => {
    const transport: Transport = { fetch: async () => new Response("no", { status: 503 }) };
    await expect(createLorasApi(transport).list()).rejects.toBeInstanceOf(HttpError);
  });
});
