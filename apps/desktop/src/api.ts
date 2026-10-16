// SPDX-License-Identifier: AGPL-3.0-only
// One transport, one run client and one models client for the whole window, so hooks that depend on
// them see stable functions.
import {
  createAssistantApi,
  createNotebooksApi,
  createRunClient,
  createVoiceApi,
} from "@wasifyai/client";
import { createDiscoveryApi } from "./discovery";
import { engineSession } from "./engine";
import { createHubApi } from "./hub";
import { createLanguageApi } from "./language";
import { createLorasApi } from "./loras";
import { createModelsApi } from "./models";
import { createEngineTransport } from "./transport";

export const transport = createEngineTransport(engineSession);
export const client = createRunClient(transport);
export const modelsApi = createModelsApi(transport);
export const discoveryApi = createDiscoveryApi(transport);
export const languageApi = createLanguageApi(transport);
export const hubApi = createHubApi(transport);
export const assistantApi = createAssistantApi(transport);
export const lorasApi = createLorasApi(transport);
export const notebooksApi = createNotebooksApi(transport);
export const voiceApi = createVoiceApi(transport);
