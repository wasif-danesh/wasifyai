// SPDX-License-Identifier: AGPL-3.0-only
// One transport, one run client and one models client for the whole window, so hooks that depend on
// them see stable functions.
import {
  createAssistantApi,
  createComponentsApi,
  createConnectionsApi,
  createCreationsApi,
  createExternalApi,
  createNotebooksApi,
  createOwnKeysApi,
  createRunClient,
  createStylesApi,
  createVoiceApi,
} from "@wasifyai/client";
import { createDiscoveryApi } from "./discovery";
import { engineSession } from "./engine";
import { createHubApi } from "./hub";
import { createLanguageApi } from "./language";
import { createModelsApi } from "./models";
import { createEngineTransport } from "./transport";

export const transport = createEngineTransport(engineSession);
export const client = createRunClient(transport);
export const connectionsApi = createConnectionsApi(transport);
export const ownKeysApi = createOwnKeysApi(transport);
export const componentsApi = createComponentsApi(transport);
export const externalApi = createExternalApi(transport);
export const modelsApi = createModelsApi(transport);
export const discoveryApi = createDiscoveryApi(transport);
export const languageApi = createLanguageApi(transport);
export const hubApi = createHubApi(transport);
export const assistantApi = createAssistantApi(transport);
export const stylesApi = createStylesApi(transport); // the image screens' styles (ADR-0091)
export const notebooksApi = createNotebooksApi(transport);
export const voiceApi = createVoiceApi(transport);
export const creationsApi = createCreationsApi(transport);
