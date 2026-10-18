// The voice product's speeches, transcripts, music and talking videos as My creations shows them. They open the
// shared voice screens, which hold the history.

/** What a card needs of each kind. */
export type SongCard = {
  id: string;
  title: string;
  style: string;
  created_at: string;
  audio_url: string;
};
export type SpeechCard = {
  id: string;
  text: string;
  voice: string;
  seconds: number;
  created_at: string;
  audio_url: string;
};
export type TranscriptCard = {
  id: string;
  title: string;
  preview: string;
  seconds: number;
  status: "done";
  created_at: string;
};
export type LipSyncCard = {
  id: string;
  text: string;
  seconds: number;
  status: "done";
  created_at: string;
  video_url: string;
  poster_url: string | null;
};

type VoiceSpeech = {
  id: string;
  text: string;
  voice?: string | null;
  model_id?: string;
  seconds: number;
  created_at: string;
  audio_url: string;
};

type VoiceTranscript = {
  id: string;
  title: string;
  text?: string;
  seconds?: number;
  created_at: string;
};

type VoiceTrack = {
  id: string;
  title: string;
  description?: string;
  created_at: string;
  audio_url: string;
};

type VoiceClip = {
  id: string;
  title: string;
  script?: string;
  seconds: number;
  width?: number;
  height?: number;
  created_at: string;
  video_url: string;
  picture_url?: string;
};

/** Whether this deployment keeps speech, music and video in the voice product (`VOICE_ENABLED`). */
export function voiceOn(): boolean {
  return process.env.VOICE_ENABLED === "true";
}

export function speechFromVoice(s: VoiceSpeech): SpeechCard {
  return {
    id: s.id,
    text: s.text,
    voice: s.voice ?? s.model_id ?? "",
    seconds: s.seconds,
    created_at: s.created_at,
    audio_url: s.audio_url,
  };
}

export function transcriptFromVoice(t: VoiceTranscript): TranscriptCard {
  return {
    id: t.id,
    title: t.title,
    preview: (t.text ?? "").slice(0, 240),
    seconds: t.seconds ?? 0,
    status: "done",
    created_at: t.created_at,
  };
}

/** Music, a dub, a stem or an audiobook chapter the voice product kept. */
export function trackFromVoice(t: VoiceTrack): SongCard {
  return {
    id: t.id,
    title: t.title,
    style: t.description ?? "",
    created_at: t.created_at,
    audio_url: t.audio_url,
  };
}

/** A talking video the voice product kept. */
export function clipFromVoice(c: VoiceClip): LipSyncCard {
  return {
    id: c.id,
    text: c.script ?? c.title,
    seconds: c.seconds,
    status: "done",
    created_at: c.created_at,
    video_url: c.video_url,
    poster_url: c.picture_url ?? null,
  };
}
