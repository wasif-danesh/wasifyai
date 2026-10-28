// SPDX-License-Identifier: AGPL-3.0-only
import type { VideoSummary } from "@wasifyai/client";
import { VideoLibrary } from "@wasifyai/ui";
import type { Route } from "../router";
import { videos } from "../videos";

/** Every clip made on this computer: the shared library screen. */
export function VideosPage({
  go,
  onExtend,
}: {
  go: (r: Route) => void;
  onExtend?: (video: VideoSummary) => void;
}) {
  return <VideoLibrary videos={videos} canSave onCreate={() => go("video")} onExtend={onExtend} />;
}
