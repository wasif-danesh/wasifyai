// The nouns and the verb every screen uses (ADR-0093 decision 3, `design/DESIGN.md` "Voice and tone"): one word
// for each thing a person makes, and "make" for making it. Import these instead of writing the words again, so a
// screen cannot drift to "generate", "image" or "asset". `words.test.ts` keeps the drift from growing.

export const NOUNS = {
  picture: "picture",
  video: "video",
  speech: "speech",
  song: "song",
  voice: "voice",
  recording: "recording",
  transcript: "transcript",
  notebook: "notebook",
  model: "model",
  model3d: "3D model",
} as const;

export type Noun = keyof typeof NOUNS;

/** "Make the picture", "Make the song": the main button of a make screen. */
export function makeLabel(noun: Noun): string {
  return `Make the ${NOUNS[noun]}`;
}

/** "Making your picture…": the working state's label. */
export function makingLabel(noun: Noun): string {
  return `Making your ${NOUNS[noun]}…`;
}

/** "Your picture appears here.": the stage's empty state. */
export function appearsHere(noun: Noun): string {
  return `Your ${NOUNS[noun]} appears here.`;
}

/** "Pictures", "Songs": the plural, for a filter or a strip's title. */
export function plural(noun: Noun): string {
  const word = NOUNS[noun];
  return word.endsWith("h") ? `${word}es` : `${word}s`;
}

/** The words a screen must not use for what a person makes, and what to say instead. */
export const AVOID: Record<string, string> = {
  generate: "make",
  image: "picture",
  asset: "picture, video, song…",
  Takes: "how many",
};
