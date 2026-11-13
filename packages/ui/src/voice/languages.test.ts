import { describe, expect, it } from "vitest";
import {
  LANGUAGES,
  baseCode,
  languageLabel,
  languageName,
  languagesOf,
  speaks,
  spokenCodes,
  voicesFor,
} from "./languages";

describe("the shared language list", () => {
  it("names Bengali and the chosen Indian languages, with their own names", () => {
    for (const code of ["bn", "hi", "mr", "te", "ta", "gu"]) {
      expect(LANGUAGES.some((l) => l.code === code)).toBe(true);
    }
    expect(languageLabel("bn")).toBe("Bengali (বাংলা)");
    expect(languageLabel("en-GB")).toBe("English");
    expect(languageName("xx")).toBe("xx");
  });

  it("compares codes by their base", () => {
    expect(baseCode("pt_BR")).toBe("pt");
    expect(speaks(["en-us", "en-gb"], "EN")).toBe(true);
    expect(speaks(["en-us"], "bn")).toBe(false);
    expect(speaks(["multi"], "bn")).toBe(true);
    expect(spokenCodes(["multi"])).toHaveLength(LANGUAGES.length);
  });

  it("gives a model's voices for a language", () => {
    const model = {
      languages: ["en-us", "hi", "bn"],
      voices: [
        { id: "af_heart", language: "en-us" },
        { id: "hf_alpha", language: "hi" },
        { id: "any", language: "" },
      ],
    };
    expect(voicesFor(model, "hi").map((v) => v.id)).toEqual(["hf_alpha", "any"]);
    expect(voicesFor(model, "bn").map((v) => v.id)).toEqual(["any"]);
    expect(voicesFor(model, "fr")).toEqual([]);
  });

  it("lists the languages some model speaks, by English name", () => {
    expect(languagesOf([{ languages: ["hi", "en-us"] }, { languages: ["bn", "xx"] }])).toEqual([
      "bn",
      "en",
      "hi",
    ]);
  });
});
