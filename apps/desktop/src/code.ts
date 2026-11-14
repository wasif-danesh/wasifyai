// SPDX-License-Identifier: AGPL-3.0-only
// Coding sessions (ADR-0101): the shared API (packages/client) on the window's transport.
import { createCodeApi } from "@wasifyai/client";
import { transport } from "./api";

export const code = createCodeApi(transport);
