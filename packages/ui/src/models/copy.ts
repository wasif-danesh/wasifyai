// SPDX-License-Identifier: AGPL-3.0-only
// What a person is told about each model, in a line with no jargon (ADR-0086). English only in v1. A model that is
// not here is shown with a line made from what the engine knows. Keep each line to one sentence: what it does and
// what it is good at. The desktop and the web show the same lines.
import type { Tier } from "./types";

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

/** "huggingface.co" from a source address, or null when it is not one. */
export function hostOf(source: string | null | undefined): string | null {
  if (!source) return null;
  try {
    return new URL(source.includes("://") ? source : `https://${source}`).hostname;
  } catch {
    return null;
  }
}

/**
 * A model's name as a person reads it (the UI plan's principle 5: never a raw tag). A tag from a local server
 * ("qwen3.8:27b-mlx") or a file name ("Qwen3-8B-Q4_K_M.gguf") becomes "Qwen3.8 27B (MLX)" or "Qwen3 8B (Q4_K_M)"; a
 * name that is already a title is left as it is.
 */
export function displayName(name: string): string {
  const raw = name.trim();
  // a file another tool keeps by its hash ("llamacpp:9ba9cc2b…") has no name to read: say so, never the hash
  if (/[0-9a-f]{24,}/i.test(raw)) return "Unnamed model";
  const looksLikeTag = /[:/]|\.gguf$|\.safetensors$/i.test(raw) || /^[a-z0-9]+[-_.]/.test(raw);
  if (!looksLikeTag || /\s/.test(raw)) return raw;
  const base = raw
    .split("/")
    .pop()
    ?.replace(/\.(gguf|safetensors)$/i, "") as string;
  const [family, variant = ""] = base.includes(":") ? base.split(":", 2) : [base, ""];
  // a quantization (Q4_K_M) is one piece; anything else splits on - and _
  const parts = `${family}${variant ? `-${variant}` : ""}`
    .split("-")
    .flatMap((p) => (/^q\d/i.test(p) ? [p] : p.split("_")))
    .filter(Boolean);
  const words: string[] = [];
  const extra: string[] = [];
  for (const p of parts) {
    if (/^[ae]?\d+(\.\d+)?[bm]$/i.test(p))
      words.push(p.toUpperCase()); // 8B, E4B (Gemma), A3B
    else if (/^(q\d.*|fp\d+|bf16|int\d|mlx|gguf|it|instruct|qat|latest|awq|gptq)$/i.test(p))
      extra.push(p.toUpperCase());
    else words.push(p.charAt(0).toUpperCase() + p.slice(1));
  }
  const tail = extra.filter((e) => e !== "LATEST" && e !== "GGUF").join(" ");
  return `${words.join(" ")}${tail ? ` (${tail})` : ""}`;
}
