// SPDX-License-Identifier: AGPL-3.0-only
// The styles (LoRAs) the image engine can apply (`GET /desktop/loras`, stage C): the ones ready now, and the
// ones one click away because their folder is not read yet.
import type { Transport } from "@wasifyai/client";
import { HttpError } from "@wasifyai/client";

export type LoraRow = {
  id: string;
  /** the name a workflow uses: relative to a `loras` folder */
  name: string;
  title: string;
  family: string;
  size: number;
  tool: string;
  reason: string;
  use: string;
};

export type LoraList = { ready: LoraRow[]; available: LoraRow[] };

export function createLorasApi(transport: Transport) {
  return {
    async list(): Promise<LoraList> {
      const res = await transport.fetch("/desktop/loras");
      if (!res.ok) throw new HttpError(res.status, `The engine answered ${res.status}`);
      return (await res.json()) as LoraList;
    },
  };
}

export type LorasApi = ReturnType<typeof createLorasApi>;
