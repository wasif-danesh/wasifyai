// SPDX-License-Identifier: AGPL-3.0-only
// Training (ADR-0073): the shared API (packages/client) on the window's transport.
import { createTrainingApi } from "@wasifyai/client";
import { transport } from "./api";

export const training = createTrainingApi(transport);
