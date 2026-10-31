// SPDX-License-Identifier: AGPL-3.0-only
// Motion graphics (ADR-0077): the shared screen on this window's engine.
import { ModelSelect, type ModelSelectHandle, VideoBuilder, useChoicesFor } from "@wasifyai/ui";
import { useRef } from "react";
import { assistantApi, client, voiceApi } from "../api";
import { videoBuilder } from "../builder";
import { ChatStart } from "../choices/ChatStart";
import { images } from "../images";
import type { Route } from "../router";
import { videos } from "../videos";

export function VideoBuilderPage({ go }: { go: (r: Route) => void }) {
  const choices = useChoicesFor("chat");
  const picker = useRef<ModelSelectHandle>(null);
  return (
    <VideoBuilder
      api={videoBuilder}
      videos={videos}
      canSave
      onOpenLibrary={() => go("videos")}
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
