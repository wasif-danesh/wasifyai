// The voice screens of the web app (the shared pages of packages/ui) and which of them a deployment offers.
// The engine behind the service decides: hosted models give speech and transcription; a service on a
// machine that has the local models gives the rest too. A screen is offered when a ready model can do what
// it needs, so the menu never links to a screen that cannot work.
import type { VoiceTarget } from "@wasifyai/ui";

export type VoiceScreenName =
  | "speak"
  | "transcribe"
  | "voices"
  | "convert"
  | "edit"
  | "dub"
  | "audiobook"
  | "lipsync"
  | "music"
  | "tracks"
  | "lyrics"
  | "separate";

export type VoiceScreen = {
  /** the menu item it answers */
  item: string;
  title: string;
  /** tasks a ready model must have: all of the first list, or any of `anyOf` */
  needs: readonly string[];
  anyOf?: readonly string[];
};

export const VOICE_SCREENS: Record<VoiceScreenName, VoiceScreen> = {
  speak: { item: "voice.speak", title: "Text to speech", needs: ["speak"] },
  transcribe: { item: "voice.transcribe", title: "Speech to text", needs: ["transcribe"] },
  voices: { item: "voice.voices", title: "Voices", needs: [], anyOf: ["design", "clone"] },
  convert: { item: "voice.convert", title: "Change a voice", needs: ["convert"] },
  edit: { item: "voice.edit", title: "Edit speech", needs: ["edit"] },
  dub: { item: "voice.dub", title: "Dub a recording", needs: ["speak", "transcribe"] },
  audiobook: { item: "voice.audiobook", title: "Audiobook", needs: ["speak"] },
  lipsync: { item: "voice.lipsync", title: "Lip sync", needs: ["lipsync"] },
  music: { item: "music.create", title: "Create music", needs: ["music"] },
  tracks: { item: "music.library", title: "Your music", needs: ["music"] },
  lyrics: { item: "music.lyrics", title: "Lyrics", needs: ["music"] },
  separate: { item: "music.separate", title: "Split into parts", needs: ["separate"] },
};

export const isVoiceScreen = (name: string): name is VoiceScreenName =>
  Object.hasOwn(VOICE_SCREENS, name);

export const voicePath = (name: VoiceScreenName) => `/voice/${name}`;

/** What a page asks to open (the desktop's names) and where that is on the web. */
export const TARGETS: Record<VoiceTarget, VoiceScreenName> = {
  speak: "speak",
  music: "music",
  tracks: "tracks",
  separate: "separate",
  convert: "convert",
  speechedit: "edit",
  voices: "voices",
  models: "speak", // models are chosen by the deployment, so no page asks for this
};

type ListedModel = { tasks: string[]; state: string };

/** The screens a list of models (with their state) makes possible. */
export function offeredScreens(models: readonly ListedModel[]): VoiceScreenName[] {
  const ready = new Set(models.filter((m) => m.state === "ready").flatMap((m) => m.tasks));
  return (Object.keys(VOICE_SCREENS) as VoiceScreenName[]).filter((name) => {
    const s = VOICE_SCREENS[name];
    return s.needs.every((t) => ready.has(t)) && (!s.anyOf || s.anyOf.some((t) => ready.has(t)));
  });
}
