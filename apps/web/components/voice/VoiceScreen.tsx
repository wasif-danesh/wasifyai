"use client";

import { webVoice } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import { TARGETS, type VoiceScreenName, voicePath } from "@/lib/voice-screens";
import {
  AudiobookPage,
  DubPage,
  LipSyncPage,
  LyricsPage,
  MusicPage,
  type Remembered,
  SpeakPage,
  ToolPage,
  TracksPage,
  TranscribePage,
  type VoicePageProps,
  type VoiceTarget,
  VoicesPage,
} from "@wasifyai/ui";
import { useRouter } from "next/navigation";

// Small choices (the model last used) and hand-offs between screens, kept in this browser. Never required.
const remembered: Remembered = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // forgotten
    }
  },
};

/** One voice screen: the same page the desktop window shows, with the web's engine and navigation. */
export function VoiceScreen({ screen }: { screen: VoiceScreenName }) {
  const router = useRouter();
  const props: VoicePageProps = {
    api: webVoice,
    runs: webClient,
    remembered,
    place: "service",
    go: (to: VoiceTarget) => router.push(voicePath(TARGETS[to])),
  };
  switch (screen) {
    case "speak":
      return <SpeakPage {...props} />;
    case "transcribe":
      return <TranscribePage {...props} />;
    case "voices":
      return <VoicesPage {...props} />;
    case "convert":
      return <ToolPage tool="convert" {...props} />;
    case "edit":
      return <ToolPage tool="edit" {...props} />;
    case "separate":
      return <ToolPage tool="separate" {...props} />;
    case "dub":
      return <DubPage {...props} />;
    case "audiobook":
      return <AudiobookPage {...props} />;
    case "lipsync":
      return <LipSyncPage {...props} />;
    case "music":
      return <MusicPage {...props} />;
    case "tracks":
      return <TracksPage {...props} />;
    case "lyrics":
      return <LyricsPage {...props} />;
  }
}
