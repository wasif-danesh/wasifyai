"use client";

import { webModel3d } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import { Model3d } from "@wasifyai/ui";

/** Make a 3D model: the shared screen (also the desktop's), talking to the BFF. The work is done on the service's worker. */
export function Model3dScreen() {
  return (
    <Model3d
      api={webModel3d}
      images={webClient}
      place="service"
      downloadHref={(m) => `/api/products/wasifyai-model3d/m3d/models/${m.id}/file`}
    />
  );
}
