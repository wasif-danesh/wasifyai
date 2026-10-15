// SPDX-License-Identifier: AGPL-3.0-only
// One transport, one run client and one models client for the whole window, so hooks that depend on
// them see stable functions.
import { createRunClient } from "@wasifyai/client";
import { engineSession } from "./engine";
import { createModelsApi } from "./models";
import { createEngineTransport } from "./transport";

export const transport = createEngineTransport(engineSession);
export const client = createRunClient(transport);
export const modelsApi = createModelsApi(transport);
