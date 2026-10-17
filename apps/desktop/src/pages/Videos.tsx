// SPDX-License-Identifier: AGPL-3.0-only
import { VideoLibrary } from "@wasifyai/ui";
import type { Route } from "../router";
import { videos } from "../videos";

/** Every clip made on this computer: the shared library screen. */
export function VideosPage({ go }: { go: (r: Route) => void }) {
  return <VideoLibrary videos={videos} canSave onCreate={() => go("video")} />;
}
