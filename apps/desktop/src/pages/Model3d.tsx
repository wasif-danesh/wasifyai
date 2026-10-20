// SPDX-License-Identifier: AGPL-3.0-only
// 3D models (ADR-0080, experimental, behind a Labs switch): the shared screen on this window's engine.
import { Button, Model3d, Notice, useModel3dLabs } from "@wasifyai/ui";
import { client } from "../api";
import { model3d } from "../model3d";
import type { Route } from "../router";

export function Model3dPage({ go }: { go: (r: Route) => void }) {
  const [on, setOn] = useModel3dLabs();
  if (!on) {
    return (
      <div className="mx-auto grid w-full max-w-3xl gap-4 px-6 pt-16 pb-12">
        <h1 className="font-semibold text-2xl">3D model</h1>
        <Notice
          tone="info"
          title="3D models are switched off"
          actions={<Button onClick={() => setOn(true)}>Switch it on</Button>}
        >
          It is still being built, so it lives in Labs. You can switch it off again in Settings,
          under Labs; nothing you made is lost.
        </Notice>
      </div>
    );
  }
  return <Model3d api={model3d} images={client} canSave onOpenLibrary={() => go("library")} />;
}
