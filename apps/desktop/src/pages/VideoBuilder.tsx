// SPDX-License-Identifier: AGPL-3.0-only
// Video Builder (ADR-0077, experimental, behind a Labs switch): the shared screen on this window's engine.
import { Button, Notice, VideoBuilder, useVideoBuilderLabs } from "@wasifyai/ui";
import { videoBuilder } from "../builder";
import type { Route } from "../router";
import { videos } from "../videos";

export function VideoBuilderPage({ go }: { go: (r: Route) => void }) {
  const [on, setOn] = useVideoBuilderLabs();
  if (!on) {
    return (
      <div className="mx-auto grid w-full max-w-3xl gap-4 px-6 pt-16 pb-12">
        <h1 className="font-semibold text-2xl">Video Builder</h1>
        <Notice
          tone="info"
          title="Video Builder is switched off"
          actions={<Button onClick={() => setOn(true)}>Switch it on</Button>}
        >
          It is still being built, so it lives in Labs. You can switch it off again in Settings,
          under Labs; nothing you made is lost.
        </Notice>
      </div>
    );
  }
  return (
    <VideoBuilder api={videoBuilder} videos={videos} canSave onOpenLibrary={() => go("videos")} />
  );
}
