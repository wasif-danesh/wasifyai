// SPDX-License-Identifier: AGPL-3.0-only
// 3D models (ADR-0080): the shared API (packages/client) on the window's transport.
import { createModel3dApi } from "@wasifyai/client";
import { transport } from "./api";

export const model3d = createModel3dApi(transport);
