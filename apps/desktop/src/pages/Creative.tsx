// SPDX-License-Identifier: AGPL-3.0-only
// Creative Studio (ADR-0090): the shared screen on this window's engine. The Image and Video tabs of its Make panel
// and Music tabs are the same make screens as the Images, Video and Music pages, in one column, and what they make
// goes to the project. Save a copy of the finished video is the engine's, like the Video page's.
import type { ImageMode, VideoMode } from "@wasifyai/client";
import {
  Creative,
  type CreativeScreen,
  ImageWorkspace,
  LipSyncWorkspace,
  type MakePanelMakers,
  ModelSelect,
  type ModelSelectHandle,
  MusicWorkspace,
  Notice,
  Segmented,
  SpeakWorkspace,
  VideoWorkspace,
  useChoicesFor,
} from "@wasifyai/ui";
import { useMemo, useRef, useState } from "react";
import { assistantApi, client, creationsApi, stylesApi, voiceApi } from "../api";
import { ChatStart } from "../choices/ChatStart";
import { useGroupReady } from "../choices/use-ready";
import { creative } from "../creative";
import { useImageEngine, useModelOf } from "../engine-hooks";
import { images } from "../images";
import { remembered } from "../remember";
import type { Route } from "../router";
import { useVideoLooks } from "../video-looks";
import { videos } from "../videos";

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

const voices = async () => (await voiceApi.voices()).map((v) => ({ id: v.id, name: v.name }));

const SCREENS: Record<CreativeScreen, Route> = {
  image: "create",
  video: "video",
  voice: "speak",
  music: "music",
  titles: "videobuilder",
  model3d: "model3d",
};

const IMAGE_MODES = [
  { value: "text", label: "Create" },
  { value: "image", label: "Edit" },
  { value: "inpaint", label: "Inpaint" },
  { value: "reference", label: "Reference" },
];
const VIDEO_MODES = [
  { value: "text", label: "Create" },
  { value: "image", label: "Animate" },
  { value: "extend", label: "Extend" },
  { value: "lipsync", label: "Lip sync" },
];
type VideoMakeMode = Exclude<VideoMode, "import"> | "lipsync";

function fitOf(model: ReturnType<typeof useModelOf>, real: boolean) {
  const tooBig = real && model?.fit?.verdict === "too_big";
  const tight = real && model?.fit?.verdict === "tight";
  return {
    blockedReason: tooBig && model?.fit ? `${model.title} will not fit. ${model.fit.reason}` : null,
    notices:
      tight && model?.fit ? (
        <Notice tone="warn" title="This computer is tight on memory">
          {model.fit.reason}
        </Notice>
      ) : null,
  };
}

function ImageMaker({
  onMade,
  ensure,
  keyed,
  go,
}: {
  onMade: (id: string) => void;
  ensure: () => boolean;
  keyed: boolean;
  go: (r: Route) => void;
}) {
  const [mode, setMode] = useState<ImageMode>("text");
  const model = useModelOf("wasifyai-image");
  const engine = useImageEngine();
  const { blockedReason, notices } = fitOf(model, engine?.state === "installed" && !keyed);
  return (
    <>
      <div className="overflow-x-auto border-b p-2">
        <Segmented
          label="What to make"
          size="sm"
          value={mode}
          onValueChange={(v) => setMode(v as ImageMode)}
          options={IMAGE_MODES}
        />
      </div>
      <div className="min-h-0 flex-1">
        <ImageWorkspace
          key={mode}
          panel
          mode={mode}
          runs={client}
          images={images}
          notices={notices}
          beforeMake={ensure}
          onMade={onMade}
          onOpenLibrary={() => go("library")}
          stylesApi={stylesApi}
          onOpenFolders={() => go("settings")}
          canSave
          blockedReason={blockedReason}
        />
      </div>
    </>
  );
}

function VideoMaker({
  onMade,
  ensure,
  keyed,
  go,
}: {
  onMade: (id: string, kind?: string) => void;
  ensure: () => boolean;
  keyed: boolean;
  go: (r: Route) => void;
}) {
  const [mode, setMode] = useState<VideoMakeMode>("text");
  const model = useModelOf("wasifyai-video");
  const engine = useImageEngine();
  const looks = useVideoLooks();
  const { blockedReason, notices } = fitOf(model, engine?.state === "installed" && !keyed);
  return (
    <>
      <div className="overflow-x-auto border-b p-2">
        <Segmented
          label="What to make"
          size="sm"
          value={mode}
          onValueChange={(v) => setMode(v as VideoMakeMode)}
          options={VIDEO_MODES}
        />
      </div>
      <div className="min-h-0 flex-1">
        {mode === "lipsync" ? (
          <LipSyncWorkspace
            panel
            api={voiceApi}
            runs={client}
            onGetModel={() => go("models")}
            onMade={(id) => onMade(id, "lipsync")}
          />
        ) : (
          <VideoWorkspace
            key={mode}
            panel
            mode={mode}
            runs={client}
            videos={videos}
            canSave
            hint="A 5 second clip takes a few minutes on a fast Mac. It is made on this computer."
            onOpenLibrary={() => go("videos")}
            blockedReason={blockedReason}
            beforeMake={ensure}
            onMade={onMade}
            looks={looks}
            notices={notices}
          />
        )}
      </div>
    </>
  );
}

// the same model as the Music page uses
const MUSIC_MODEL = "wasifyai.music.model";

async function addFile(file: File) {
  if (file.type.startsWith("image/")) {
    return { kind: "image", id: (await images.importImage(file)).id };
  }
  if (file.type.startsWith("video/")) {
    return { kind: "video", id: (await videos.importVideo(file)).id };
  }
  return { kind: "track", id: (await creationsApi.addRecording(file)).id };
}

export function CreativePage({ go }: { go: (r: Route) => void }) {
  const choices = useChoicesFor("chat");
  const picker = useRef<ModelSelectHandle>(null);
  const imageChoices = useChoicesFor("images");
  const imagePicker = useRef<ModelSelectHandle>(null);
  const image = useGroupReady(imageChoices, imagePicker);
  const videoChoices = useChoicesFor("video");
  const videoPicker = useRef<ModelSelectHandle>(null);
  const video = useGroupReady(videoChoices, videoPicker);
  const makers = useMemo<MakePanelMakers>(
    () => ({
      image: (onMade) => (
        <ImageMaker onMade={onMade} ensure={image.ensure} keyed={image.keyed} go={go} />
      ),
      video: (onMade) => (
        <VideoMaker onMade={onMade} ensure={video.ensure} keyed={video.keyed} go={go} />
      ),
      voice: (onMade) => (
        <SpeakWorkspace
          panel
          api={voiceApi}
          runs={client}
          onGetModel={() => go("models")}
          onMade={(id) => onMade(id, "speech")}
        />
      ),
      music: (onMade) => (
        <MusicWorkspace
          panel
          onMade={onMade}
          api={voiceApi}
          runs={client}
          onGetModel={() => go("models")}
          initialModel={remembered.get(MUSIC_MODEL)}
          onModelChosen={(id) => remembered.set(MUSIC_MODEL, id)}
        />
      ),
    }),
    [image.ensure, image.keyed, video.ensure, video.keyed, go],
  );
  return (
    <Creative
      api={creative}
      songs={songs}
      voices={voices}
      model={<ModelSelect group="chat" api={choices} handleRef={picker} />}
      modelOfTab={(tab) =>
        tab === "image" ? (
          <ModelSelect group="images" api={imageChoices} handleRef={imagePicker} />
        ) : tab === "video" ? (
          <ModelSelect group="video" api={videoChoices} handleRef={videoPicker} />
        ) : undefined
      }
      makers={makers}
      addFile={addFile}
      saveVideo={(id) => videos.exportCopy(id)}
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
