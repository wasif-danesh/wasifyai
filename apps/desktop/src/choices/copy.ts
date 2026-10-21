// SPDX-License-Identifier: AGPL-3.0-only
// What a person is told about each model, in a line with no jargon (ADR-0086). English only in v1. A model that is
// not here is shown with a line made from what the engine knows. Keep each line to one sentence: what it does and
// what it is good at.
import type { Tier } from "@wasifyai/ui";

export type Copy = { plain: string; tier?: Tier };

export const COPY: Record<string, Copy> = {
  // images and video
  "flux2-klein-4b": {
    plain:
      "Makes and changes pictures from your words: create, edit, paint over a part, or combine two pictures.",
  },
  "ltx-video-2b": {
    plain: "Makes 5 and 8 second videos from your words or from a picture, and carries a video on.",
  },
  // voice
  "kokoro-82m": {
    plain: "A small, fast voice that reads text aloud in natural English. Good for most uses.",
  },
  "qwen3-tts-0.6b-base": {
    plain: "Copies a voice from a short, clean recording of it, then speaks new words in it.",
  },
  "qwen3-tts-1.7b-voicedesign": {
    plain: "Designs a new voice from a description, such as a calm older man.",
  },
  voxcpm2: {
    plain: "Speaks, copies voices and designs voices in one model: richer, but heavier.",
    tier: "also",
  },
  "tone-color-vc": {
    plain: "Changes a recording into another voice, from a short sample of that voice.",
  },
  meanvc2: { plain: "Another voice changer: light and quick.", tier: "also" },
  "dots-tts-edit": {
    plain: "Changes words inside a recording of speech without recording it again.",
  },
  // listening
  "parakeet-tdt-0.6b-v3": {
    plain: "Turns speech into text with times. Fast and accurate, in many languages.",
  },
  // music
  "ace-step-1.5-turbo": {
    plain: "Makes whole songs, with singing, from a description and lyrics.",
  },
  "ace-step-1.5-turbo-comfyui": {
    plain: "The same song maker, run on the image engine: larger and slower to start.",
    tier: "advanced",
  },
  "stable-audio-3-small-music": {
    plain: "Makes short pieces of music without singing: small and quick.",
    tier: "also",
  },
  "stable-audio-3-small-sfx": {
    plain: "Makes sound effects from a description, such as rain on a window.",
  },
  htdemucs: { plain: "Splits a song into voice, drums, bass and the rest." },
  "htdemucs-6stems": {
    plain: "Splits a song into six parts, adding guitar and piano.",
    tier: "also",
  },
  "mel-band-roformer": {
    plain: "Takes the singing voice out of a song, cleanly.",
    tier: "also",
  },
  // faces
  "musetalk-v15": { plain: "Makes a picture talk, with lips that follow a recording." },
  // documents
  "bge-small-en-v1.5": {
    plain: "Lets notebooks search your documents by meaning. Small and quick.",
  },
};

/** The line for a model, or a plain fallback when it has none. */
export function plainFor(id: string, title: string, fallback?: string): string {
  return COPY[id]?.plain ?? fallback ?? `${title}.`;
}

export type ChatShelfItem = {
  repo: string;
  title: string;
  plain: string;
  /** the size of the usual 4-bit file, and the memory it needs, as measured (hub-shelf.yaml) */
  bytes: number;
  memoryGb: number;
  licence: string;
  tier?: Tier;
};

/**
 * The chat models worth offering (services/api/.../hub-shelf.yaml has the measurements). Sizes are the usual file's;
 * the exact files are read from Hugging Face when the download starts. Qwen3.5 9B joins once its checks pass (ADR-0078).
 */
export const CHAT_SHELF: ChatShelfItem[] = [
  {
    repo: "unsloth/Qwen3-4B-GGUF",
    title: "Qwen3 4B",
    plain: "Answers questions and writes well on most computers. A good place to start.",
    bytes: 2.5e9,
    memoryGb: 4,
    licence: "Apache-2.0",
  },
  {
    repo: "unsloth/Qwen3-8B-GGUF",
    title: "Qwen3 8B",
    plain: "Fuller answers than the 4B, a little slower. Needs 16 GB of memory or more.",
    bytes: 5e9,
    memoryGb: 6.5,
    licence: "Apache-2.0",
    tier: "also",
  },
  {
    repo: "unsloth/Qwen3-0.6B-GGUF",
    title: "Qwen3 0.6B",
    plain: "Tiny and very fast, for small computers. Simple answers only.",
    bytes: 0.4e9,
    memoryGb: 1,
    licence: "Apache-2.0",
    tier: "also",
  },
  {
    repo: "unsloth/gpt-oss-20b-GGUF",
    title: "gpt-oss 20B",
    plain: "A large model that shows its reasoning. Needs 32 GB of memory or more.",
    bytes: 11e9,
    memoryGb: 14,
    licence: "Apache-2.0",
    tier: "advanced",
  },
];

/** The chat model to offer first on a computer with this much memory. */
export function recommendedChat(memoryBytes: number | null): string {
  if (memoryBytes !== null && memoryBytes < 6e9) return "unsloth/Qwen3-0.6B-GGUF";
  if (memoryBytes !== null && memoryBytes >= 16e9) return "unsloth/Qwen3-8B-GGUF";
  return "unsloth/Qwen3-4B-GGUF";
}

/** "huggingface.co" from a source address, or null when it is not one. */
export function hostOf(source: string | null | undefined): string | null {
  if (!source) return null;
  try {
    return new URL(source.includes("://") ? source : `https://${source}`).hostname;
  } catch {
    return null;
  }
}
