import { describe, expect, it } from "vitest";
import { resolveWebItem } from "./menu";
import { VOICE_SCREENS, isVoiceScreen, offeredScreens } from "./voice-screens";

const model = (tasks: string[], state = "ready") => ({ tasks, state });

describe("which voice screens a service offers", () => {
  it("offers speech and transcription from hosted models, and nothing that needs more", () => {
    const offered = offeredScreens([model(["speak"]), model(["transcribe"])]);
    expect(offered).toEqual(["speak", "transcribe", "dub", "audiobook"]);
  });

  it("offers every screen when a ready model does each task", () => {
    const tasks = ["speak", "transcribe", "design", "clone", "convert", "edit", "music"];
    const offered = offeredScreens([
      ...tasks.map((t) => model([t])),
      model(["separate", "lipsync"]),
    ]);
    expect(offered).toHaveLength(Object.keys(VOICE_SCREENS).length);
  });

  it("does not offer a screen for a model that is not ready", () => {
    expect(offeredScreens([model(["music"], "can_install"), model(["speak"])])).toEqual([
      "speak",
      "audiobook",
    ]);
  });

  it("offers Voices for either design or clone", () => {
    expect(offeredScreens([model(["clone"])])).toEqual(["voices"]);
  });

  it("knows its screen names", () => {
    expect(isVoiceScreen("music")).toBe(true);
    expect(isVoiceScreen("constructor")).toBe(false);
  });
});

describe("the menu with voice screens", () => {
  const item = (id: string, served: Parameters<typeof resolveWebItem>[2], path = "/") =>
    resolveWebItem(path, null, served)(id) as { href?: string } | undefined;

  it("links an offered screen, and a screen that is not offered is not linked", () => {
    const on = { voiceScreens: ["music", "tracks", "separate"] as const };
    expect(item("music.create", on)?.href).toBe("/voice/music");
    expect(item("music.library", on)?.href).toBe("/voice/tracks");
    expect(item("music.separate", on)?.href).toBe("/voice/separate");
    expect(item("music.lyrics", on)).toBeUndefined();
    expect(item("music.create", {})).toBeUndefined();
    expect(item("music.library", {})).toBeUndefined();
  });

  it("marks the page being shown", () => {
    const on = { voiceScreens: ["convert"] as const };
    expect(
      (resolveWebItem("/voice/convert", null, on)("voice.convert") as { current?: boolean })
        .current,
    ).toBe(true);
  });
});
