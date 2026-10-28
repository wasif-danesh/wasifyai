// SPDX-License-Identifier: AGPL-3.0-only
// Create, Animate and Extend (ADR-0037): a clip from words, from a picture and what should move, or one of
// your videos carried on. The shared make screen with this window's model button (in the top bar) and setup notices.
import type { VideoMode, VideoSummary } from "@wasifyai/client";
import {
  ModelSelect,
  type ModelSelectHandle,
  Notice,
  VideoWorkspace,
  useChoicesFor,
} from "@wasifyai/ui";
import { useRef } from "react";
import { client } from "../api";
import { useGroupReady } from "../choices/use-ready";
import { useImageEngine, useModelOf } from "../engine-hooks";
import type { Route } from "../router";
import { useVideoLooks } from "../video-looks";
import { videos } from "../videos";

type PageMode = Exclude<VideoMode, "import">;

export function VideoPage({
  mode,
  go,
  onExtendThis,
  sourceImage,
  sourceVideo,
}: {
  mode: PageMode;
  go: (r: Route) => void;
  onExtendThis?: (video: VideoSummary) => void;
  sourceImage?: { url: string; name: string; id?: string } | null;
  sourceVideo?: VideoSummary | null;
}) {
  const model = useModelOf("wasifyai-video");
  const engine = useImageEngine();
  // "Select video model": the model in use, or the way to get one (ADR-0086)
  const choices = useChoicesFor("video");
  const picker = useRef<ModelSelectHandle>(null);
  const { ensure } = useGroupReady(choices, picker);
  const looks = useVideoLooks();

  // only a real model can be too big: the placeholder engine runs anywhere
  const real = engine?.state === "installed";
  const tooBig = real && model?.fit?.verdict === "too_big";
  const tight = real && model?.fit?.verdict === "tight";

  return (
    <VideoWorkspace
      mode={mode}
      runs={client}
      videos={videos}
      header={<ModelSelect group="video" api={choices} handleRef={picker} />}
      canSave
      hint="A 5 second clip takes a few minutes on a fast Mac, and an 8 second one about twice as long. It is made on this computer."
      onOpenLibrary={() => go("videos")}
      onExtendThis={onExtendThis}
      sourceImage={sourceImage}
      sourceVideo={sourceVideo}
      blockedReason={
        tooBig && model?.fit ? `${model.title} will not fit. ${model.fit.reason}` : null
      }
      beforeMake={ensure}
      looks={looks}
      notices={
        tight && model?.fit ? (
          <Notice tone="warn" title="This computer is tight on memory">
            {model.fit.reason}
          </Notice>
        ) : null
      }
    />
  );
}
