// SPDX-License-Identifier: AGPL-3.0-only
// The user's images: the shared API (packages/client) on the window's transport.
import { createImagesApi } from "@wasifyai/client";
import { transport } from "./api";

export const images = createImagesApi(transport);
