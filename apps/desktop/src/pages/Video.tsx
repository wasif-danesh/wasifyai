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

/** the capability each screen asks for, and what it does in words (ADR-0097) */
const VERB: Record<PageMode, string> = {
  text: "video.generate",
  image: "video.animate",
  extend: "video.extend",
};
const CANNOT: Record<PageMode, string> = {
  text: "make a video from words",
  image: "animate a picture",
  extend: "extend a video",
};

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
  // "Select video model": the model in use, or the way to get one (ADR-0086)
  const choices = useChoicesFor("video");
  const picker = useRef<ModelSelectHandle>(null);
  const { ensure, keyed, chosen, cloud } = useGroupReady(choices, picker);
  const model = useModelOf("wasifyai-video", keyed ? null : chosen);
  const engine = useImageEngine();
  // the chosen model makes the clip (ADR-0097); one that cannot do this screen's work says so
  const offered = !keyed && model !== null && model.id === chosen && (model.can?.length ?? 0) > 0;
  // a cloud model says what its keys' offers can do (ADR-0100, stage CP5): Extend needs an offer that extends
  const cloudCannot = keyed && cloud !== null && !cloud.can.includes(VERB[mode]);
  const cannot = (offered && !model.can?.includes(VERB[mode])) || cloudCannot;
  const looks = useVideoLooks();

  // only a real model can be too big: the placeholder engine runs anywhere
  const real = engine?.state === "installed" && !keyed;
  const tooBig = real && model?.fit?.verdict === "too_big";
  const tight = real && model?.fit?.verdict === "tight";

  return (
    <VideoWorkspace
      mode={mode}
      runs={client}
      videos={videos}
      header={<ModelSelect group="video" api={choices} handleRef={picker} />}
      canSave
      hint={
        keyed
          ? "It is made on the cloud with your keys, by the cheapest provider that can make it."
          : "A 5 second clip takes a few minutes on a fast Mac, and an 8 second one about twice as long. It is made on this computer."
      }
      onOpenLibrary={() => go("videos")}
      onExtendThis={onExtendThis}
      sourceImage={sourceImage}
      sourceVideo={sourceVideo}
      model={offered ? model.id : null}
      blockedReason={
        cannot
          ? `${cloudCannot ? cloud?.title : model?.title} cannot ${CANNOT[mode]}${cloudCannot && mode === "extend" ? " with the keys you have" : ""}. Choose another video model above.`
          : tooBig && model?.fit
            ? `${model.title} will not fit. ${model.fit.reason}`
            : null
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
