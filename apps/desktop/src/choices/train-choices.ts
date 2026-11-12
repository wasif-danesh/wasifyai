// SPDX-License-Identifier: AGPL-3.0-only
// Where Train teaches a picture look (ADR-0100, CP10): AI Toolkit on this computer, or a cloud trainer from the
// Cloud tab with the person's key (Settings › Your keys, Train models). The Train screen's "Model to teach" then
// offers the model that trainer teaches; nothing here downloads anything.
import type { OwnKeysApi } from "@wasifyai/client";
import type { ChoiceList, ChoicesApi, ModelChoice } from "@wasifyai/ui";
import { chooseCloud, cloudOf, cloudRows, withCloud } from "./keyed";

export const TRAIN_HERE_ID = "ai-toolkit";

export const trainHereRow = (): ModelChoice => ({
  id: TRAIN_HERE_ID,
  title: "This computer (AI Toolkit)",
  plain:
    "Teaches looks on this computer with AI Toolkit, set up from the Train screen. Nothing is sent anywhere.",
  tier: "recommended",
  state: "ready",
  chosen: true,
  downloadBytes: 0,
  engineBytes: 0,
  engineName: null,
  fit: null,
  fitReason: null,
  source: "app",
});

export function trainChoices(keys?: OwnKeysApi): ChoicesApi {
  return {
    ...(keys ? { cloud: cloudOf(["train"]) } : {}),
    async list(): Promise<ChoiceList> {
      const cloud = await cloudRows(keys, "train");
      return {
        choices: withCloud([trainHereRow()], cloud),
        diskFreeBytes: null,
        memoryBytes: null,
      };
    },
    async choose(id) {
      // a cloud trainer makes Train teach there; this computer takes Train off the cloud (the keys stay)
      await chooseCloud(keys, "train", id);
    },
    async remove() {},
    async get(id) {
      await chooseCloud(keys, "train", id);
    },
  };
}
