/**
 * The languages the voice screens can name, and which of them a model and each of its voices speak
 * (docs/voice-languages-plan.md, stage L1). The engine's copy is
 * `packages/platform-sdk/src/wasifyai_platform_sdk/languages.py`; a test keeps the two equal.
 *
 * A model lists its languages as codes such as `en-us`, `pt-br` or `bn`; `multi` means it is not
 * limited. Only the base code (`en`, `pt`) is compared.
 */

export type Language = {
  code: string;
  /** the English name */
  english: string;
  /** the language's name for itself */
  own: string;
  rtl?: boolean;
};

export const MULTI = "multi";

// biome-ignore format: a table
export const LANGUAGES: readonly Language[] = [
  { code: "ar", english: "Arabic", own: "العربية", rtl: true },
  { code: "bg", english: "Bulgarian", own: "Български" },
  { code: "bn", english: "Bengali", own: "বাংলা" },
  { code: "cs", english: "Czech", own: "Čeština" },
  { code: "da", english: "Danish", own: "Dansk" },
  { code: "de", english: "German", own: "Deutsch" },
  { code: "el", english: "Greek", own: "Ελληνικά" },
  { code: "en", english: "English", own: "English" },
  { code: "es", english: "Spanish", own: "Español" },
  { code: "et", english: "Estonian", own: "Eesti" },
  { code: "fi", english: "Finnish", own: "Suomi" },
  { code: "fr", english: "French", own: "Français" },
  { code: "gu", english: "Gujarati", own: "ગુજરાતી" },
  { code: "hi", english: "Hindi", own: "हिन्दी" },
  { code: "hr", english: "Croatian", own: "Hrvatski" },
  { code: "hu", english: "Hungarian", own: "Magyar" },
  { code: "it", english: "Italian", own: "Italiano" },
  { code: "ja", english: "Japanese", own: "日本語" },
  { code: "ko", english: "Korean", own: "한국어" },
  { code: "lt", english: "Lithuanian", own: "Lietuvių" },
  { code: "lv", english: "Latvian", own: "Latviešu" },
  { code: "mr", english: "Marathi", own: "मराठी" },
  { code: "mt", english: "Maltese", own: "Malti" },
  { code: "nl", english: "Dutch", own: "Nederlands" },
  { code: "pl", english: "Polish", own: "Polski" },
  { code: "pt", english: "Portuguese", own: "Português" },
  { code: "ro", english: "Romanian", own: "Română" },
  { code: "ru", english: "Russian", own: "Русский" },
  { code: "sk", english: "Slovak", own: "Slovenčina" },
  { code: "sl", english: "Slovenian", own: "Slovenščina" },
  { code: "sv", english: "Swedish", own: "Svenska" },
  { code: "ta", english: "Tamil", own: "தமிழ்" },
  { code: "te", english: "Telugu", own: "తెలుగు" },
  { code: "uk", english: "Ukrainian", own: "Українська" },
  { code: "zh", english: "Chinese", own: "中文" },
];

const BY_CODE: ReadonlyMap<string, Language> = new Map(LANGUAGES.map((l) => [l.code, l]));

/** `en-us`, `EN` and `pt_BR` are `en`, `en` and `pt`. */
export function baseCode(code: string): string {
  return code.trim().toLowerCase().replace(/_/g, "-").split("-")[0] ?? code;
}

export function findLanguage(code: string): Language | undefined {
  return BY_CODE.get(baseCode(code));
}

/** The English name, or the code itself when the app cannot name it. */
export function languageName(code: string): string {
  return findLanguage(code)?.english ?? code;
}

/** What a list shows: `Bengali (বাংলা)`, or `English` where the two names are the same. */
export function languageLabel(code: string): string {
  const l = findLanguage(code);
  if (!l) return code;
  return l.own === l.english ? l.english : `${l.english} (${l.own})`;
}

/** The base codes a model's `languages` stand for; `multi` is every language the app names. */
export function spokenCodes(languages: readonly string[]): string[] {
  const codes = [...new Set(languages.map(baseCode))];
  return codes.includes(MULTI) ? LANGUAGES.map((l) => l.code) : codes;
}

/** Whether a model with these `languages` speaks (or writes down) `language`. */
export function speaks(languages: readonly string[], language: string): boolean {
  const codes = languages.map(baseCode);
  return codes.includes(MULTI) || codes.includes(baseCode(language));
}

type HasVoices = {
  languages: readonly string[];
  voices: readonly { id: string; language?: string }[];
};

/** The voices of a model that speak `language`: a voice that names a language speaks only that one
 *  (a Kokoro voice speaks the language of its accent); one that names none speaks every language of
 *  the model. */
export function voicesFor<V extends { id: string; language?: string }>(
  model: { languages: readonly string[]; voices: readonly V[] },
  language: string,
): V[] {
  const want = baseCode(language);
  const every = spokenCodes(model.languages);
  return model.voices.filter((v) =>
    v.language ? baseCode(v.language) === want : every.includes(want),
  );
}

/** The languages, sorted by English name, that some of these models speak and the app can name. */
export function languagesOf(models: readonly Pick<HasVoices, "languages">[]): string[] {
  return [...new Set(models.flatMap((m) => spokenCodes(m.languages)))]
    .filter((c) => BY_CODE.has(c))
    .sort((a, b) => languageName(a).localeCompare(languageName(b)));
}
