// SPDX-License-Identifier: AGPL-3.0-only
// The user's videos: the shared API (packages/client) on the window's transport.
import { createVideosApi } from "@wasifyai/client";
import { transport } from "./api";

export const videos = createVideosApi(transport);
