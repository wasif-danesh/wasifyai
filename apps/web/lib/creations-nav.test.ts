import { describe, expect, it } from "vitest";
import { hrefOf, webCreationsNav } from "./creations-nav";

const when = "2026-10-18T00:00:00Z";

describe("where My creations opens on the web", () => {
  it("opens the shared voice screens, not the older detail pages", () => {
    const speech = {
      id: "s1",
      text: "Hi",
      voice: "alloy",
      seconds: 1,
      created_at: when,
      audio_url: "a",
    };
    expect(hrefOf({ kind: "speech", id: "s1", createdAt: when, speech })).toBe("/voice/speak");
    const song = { id: "k1", title: "Rain", style: "", created_at: when, audio_url: "a" };
    expect(hrefOf({ kind: "song", id: "k1", createdAt: when, song })).toBe("/voice/tracks");
    const lipsync = {
      id: "c1",
      text: "",
      seconds: 3,
      status: "done" as const,
      created_at: when,
      video_url: "v",
      poster_url: null,
    };
    expect(hrefOf({ kind: "lipsync", id: "c1", createdAt: when, lipsync })).toBe("/voice/lipsync");
    const transcript = {
      id: "t1",
      title: "Call",
      preview: "",
      seconds: 1,
      status: "done" as const,
      created_at: when,
    };
    expect(hrefOf({ kind: "transcript", id: "t1", createdAt: when, transcript })).toBe(
      "/voice/transcribe",
    );
  });

  it("gives an image and a video their own pages, and goes through the app's router", () => {
    const pushed: string[] = [];
    const nav = webCreationsNav((h) => pushed.push(h));
    nav.make("music");
    expect(pushed).toEqual(["/voice/music"]);
    expect(nav.href?.("video")).toBe("/video");
  });
});
