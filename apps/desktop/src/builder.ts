// SPDX-License-Identifier: AGPL-3.0-only
// Motion graphics (ADR-0077): the shared API (packages/client) on the window's transport.
import { createVideoBuilderApi } from "@wasifyai/client";
import { transport } from "./api";

export const videoBuilder = createVideoBuilderApi(transport, {
  address: async (path) => `${await transport.base()}${path}`,
});
