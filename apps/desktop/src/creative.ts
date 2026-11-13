// SPDX-License-Identifier: AGPL-3.0-only
// Creative Studio (ADR-0090): the shared API (packages/client) on the window's transport.
import { createCreativeApi } from "@wasifyai/client";
import { transport } from "./api";

export const creative = createCreativeApi(transport);
