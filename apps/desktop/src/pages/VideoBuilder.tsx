// SPDX-License-Identifier: AGPL-3.0-only
// Motion graphics (ADR-0077): the shared screen on this window's engine.
import {
  ModelSelect,
  type ModelSelectHandle,
  VideoBuilder,
  mediaLibrary,
  useChoicesFor,
} from "@wasifyai/ui";
import { useRef } from "react";
import { assistantApi, client, voiceApi } from "../api";
import { videoBuilder } from "../builder";
import { ChatStart } from "../choices/ChatStart";
import { images } from "../images";
import type { Route } from "../router";
import { videos } from "../videos";

const LIBRARY = mediaLibrary({
  images,
  videos,
  hrefOf: async (item) => {
    const page =
      item.kind === "image"
        ? (await images.get(item.id)).image_url
        : (await videos.get(item.id))?.video_url;
    if (!page) throw new Error("That is not ready yet.");
    return page;
  },
});

export function VideoBuilderPage({ go }: { go: (r: Route) => void }) {
  const choices = useChoicesFor("chat");
  const picker = useRef<ModelSelectHandle>(null);
  return (
    <VideoBuilder
      api={videoBuilder}
      videos={videos}
      canSave
      onOpenLibrary={() => go("videos")}
      library={LIBRARY}
      assistant={{
        runs: client,
        api: assistantApi,
        images,
        tracks: (id) => voiceApi.track(id),
        notices: <ChatStart picker={picker} />,
        model: <ModelSelect group="chat" api={choices} handleRef={picker} />,
        onNeedModel: () => picker.current?.open(),
        onOpenSettings: () => go("settings"),
      }}
    />
  );
}
