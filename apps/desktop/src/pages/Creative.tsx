// SPDX-License-Identifier: AGPL-3.0-only
// Creative Studio (ADR-0090): the shared screen on this window's engine.
import {
  Creative,
  type CreativeScreen,
  ModelSelect,
  type ModelSelectHandle,
  useChoicesFor,
} from "@wasifyai/ui";
import { useRef } from "react";
import { assistantApi, client, creationsApi, voiceApi } from "../api";
import { ChatStart } from "../choices/ChatStart";
import { creative } from "../creative";
import { images } from "../images";
import type { Route } from "../router";

const songs = async () => {
  const tracks = await voiceApi.tracks({ limit: 200 });
  return tracks.map((t) => ({
    id: t.id,
    title: t.title,
    seconds: t.seconds,
    lyrics: t.lyrics,
    url: t.audio_url,
  }));
};

const SCREENS: Record<CreativeScreen, Route> = {
  image: "create",
  video: "video",
  voice: "speak",
  music: "music",
  titles: "videobuilder",
  model3d: "model3d",
};

export function CreativePage({ go }: { go: (r: Route) => void }) {
  const choices = useChoicesFor("chat");
  const picker = useRef<ModelSelectHandle>(null);
  return (
    <Creative
      api={creative}
      songs={songs}
      model={<ModelSelect group="chat" api={choices} handleRef={picker} />}
      onMakeSong={() => go("music")}
      creations={creationsApi}
      onOpenScreen={(screen) => go(SCREENS[screen])}
      assistant={{
        runs: client,
        api: assistantApi,
        images,
        tracks: (id) => voiceApi.track(id),
        notices: <ChatStart picker={picker} />,
        onNeedModel: () => picker.current?.open(),
        onOpenSettings: () => go("settings"),
      }}
    />
  );
}
