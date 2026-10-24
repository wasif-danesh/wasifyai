// SPDX-License-Identifier: AGPL-3.0-only
// Motion graphics (ADR-0077): the shared screen on this window's engine.
import { VideoBuilder } from "@wasifyai/ui";
import { videoBuilder } from "../builder";
import type { Route } from "../router";
import { videos } from "../videos";

export function VideoBuilderPage({ go }: { go: (r: Route) => void }) {
  return (
    <VideoBuilder api={videoBuilder} videos={videos} canSave onOpenLibrary={() => go("videos")} />
  );
}
