"use client";

import {
  videoDownload,
  webAssistant,
  webCreations,
  webCreative,
  webImages,
  webStyles,
  webTraining,
  webVideos,
  webVoice,
} from "@/lib/library";
import { remembered } from "@/lib/remembered";
import { webClient } from "@/lib/run-client";
import type { ImageMode, VideoMode } from "@wasifyai/client";
import {
  Creative,
  type CreativeScreen as Screen,
  ImageWorkspace,
  LipSyncWorkspace,
  type MakePanelMakers,
  ModelSelect,
  MusicWorkspace,
  Segmented,
  SpeakWorkspace,
  VideoWorkspace,
  useChoicesFor,
  useImageStyles,
  useVideoLooks,
} from "@wasifyai/ui";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

// where each tool of the Make panel has its own page on the web (the desktop's are its routes)
const SCREENS: Record<Screen, string> = {
  image: "/image",
  video: "/video",
  voice: "/voice/speak",
  music: "/voice/music",
  titles: "/video/builder",
  model3d: "/image/3d",
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
// the same model as the Music page uses
const MUSIC_MODEL = "wasifyai.music.model";

const songs = async () =>
  (await webVoice.tracks({ limit: 200 })).map((t) => ({
    id: t.id,
    title: t.title,
    seconds: t.seconds,
    lyrics: t.lyrics,
    url: t.audio_url,
  }));

const voices = async () => (await webVoice.voices()).map((v) => ({ id: v.id, name: v.name }));

async function addFile(file: File) {
  if (file.type.startsWith("image/"))
    return { kind: "image", id: (await webImages.importImage(file)).id };
  if (file.type.startsWith("video/"))
    return { kind: "video", id: (await webVideos.importVideo(file)).id };
  return { kind: "track", id: (await webCreations.addRecording(file)).id };
}

/** The finished video, through the browser's own download (the desktop saves it with its Save As box). */
async function saveVideo(videoId: string) {
  const link = document.createElement("a");
  link.href = videoDownload({ videoId });
  link.download = "";
  link.click();
  return { name: `${videoId}.mp4`, path: "your browser's downloads" };
}

function ImageMaker({ onMade }: { onMade: (id: string) => void }) {
  const [mode, setMode] = useState<ImageMode>("text");
  const styles = useImageStyles(webTraining);
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
          runs={webClient}
          images={webImages}
          loras={styles}
          stylesApi={webStyles}
          stylesReadOnly
          onMade={onMade}
        />
      </div>
    </>
  );
}

function VideoMaker({ onMade }: { onMade: (id: string, kind?: string) => void }) {
  const [mode, setMode] = useState<VideoMakeMode>("text");
  const looks = useVideoLooks(webTraining);
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
            api={webVoice}
            runs={webClient}
            onMade={(id) => onMade(id, "lipsync")}
          />
        ) : (
          <VideoWorkspace
            key={mode}
            panel
            mode={mode}
            runs={webClient}
            videos={webVideos}
            hint="Takes a few minutes for 5 seconds. It is made on the service."
            looks={looks}
            onMade={onMade}
          />
        )}
      </div>
    </>
  );
}

/** Creative Studio: the shared screen (also the desktop's), talking to the BFF. Pictures, clips, speech and lip sync
 * are made by their own products on the service's workers; a song's beats on a worker with the analysis tool. */
export function CreativeScreen({ open = null }: { open?: string | null }) {
  const router = useRouter();
  const chat = useChoicesFor("chat");
  const imageChoices = useChoicesFor("images");
  const videoChoices = useChoicesFor("video");
  const makers = useMemo<MakePanelMakers>(
    () => ({
      image: (onMade) => <ImageMaker onMade={onMade} />,
      video: (onMade) => <VideoMaker onMade={onMade} />,
      voice: (onMade) => (
        <SpeakWorkspace
          panel
          api={webVoice}
          runs={webClient}
          onMade={(id) => onMade(id, "speech")}
        />
      ),
      music: (onMade) => (
        <MusicWorkspace
          panel
          api={webVoice}
          runs={webClient}
          onMade={onMade}
          initialModel={remembered.get(MUSIC_MODEL)}
          onModelChosen={(id) => remembered.set(MUSIC_MODEL, id)}
        />
      ),
    }),
    [],
  );
  const model = chat ? <ModelSelect group="chat" api={chat} /> : undefined;
  return (
    <div data-workspace className="flex h-[calc(100dvh-3rem)] min-h-[32rem] flex-col">
      <Creative
        api={webCreative}
        open={open}
        songs={songs}
        voices={voices}
        model={model}
        modelOfTab={(tab) =>
          tab === "image" && imageChoices ? (
            <ModelSelect group="images" api={imageChoices} />
          ) : tab === "video" && videoChoices ? (
            <ModelSelect group="video" api={videoChoices} />
          ) : undefined
        }
        makers={makers}
        addFile={addFile}
        saveVideo={saveVideo}
        onMakeSong={() => router.push("/voice/music")}
        creations={webCreations}
        onOpenScreen={(screen) => router.push(SCREENS[screen])}
        assistant={{
          runs: webClient,
          api: webAssistant,
          images: webImages,
          tracks: (id) => webVoice.track(id),
        }}
      />
    </div>
  );
}
