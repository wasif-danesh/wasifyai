// SPDX-License-Identifier: AGPL-3.0-only
// 3D models (ADR-0080): the shared screen on this window's engine.
import { Model3d } from "@wasifyai/ui";
import { client } from "../api";
import { model3d } from "../model3d";
import type { Route } from "../router";

export function Model3dPage({ go }: { go: (r: Route) => void }) {
  return <Model3d api={model3d} images={client} canSave onOpenLibrary={() => go("library")} />;
}
