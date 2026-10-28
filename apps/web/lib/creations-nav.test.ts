// @vitest-environment jsdom
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
    expect(hrefOf({ kind: "song", id: "k1", createdAt: when, song })).toBe("/voice/music");
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

  it("hands a picture, a clip and a track to the tools the same way the make screens do", () => {
    const pushed: string[] = [];
    const nav = webCreationsNav((h) => pushed.push(h));
    const image = {
      id: "i1",
      prompt: "A teapot",
      mode: "text" as const,
      width: 8,
      height: 8,
      created_at: when,
      image_url: "http://x/i1.png",
      thumb_url: "t",
      recipe: null,
      favourite: false,
    }; // fmt: skip
    const picture = { kind: "image" as const, id: "i1", createdAt: when, image };
    const song = { id: "k1", title: "Rain", style: "", created_at: when, audio_url: "a" };
    const track = { kind: "song" as const, id: "k1", createdAt: when, song };
    expect(nav.canUse?.(picture, "animate")).toBe(true);
    expect(nav.canUse?.(picture, "split")).toBe(false);
    expect(nav.canUse?.(track, "split")).toBe(true);
    nav.use?.(picture, "animate");
    expect(JSON.parse(sessionStorage.getItem("wasifyai:handoff:video-animate") ?? "{}")).toEqual({
      url: "http://x/i1.png",
      name: "i1.png",
      id: "i1",
    });
    nav.use?.(picture, "edit");
    nav.use?.(track, "split");
    expect(localStorage.getItem("wasifyai.tool.source")).toBe("track:k1");
    expect(pushed).toEqual(["/video/animate", "/image/edit", "/voice/separate"]);
  });

  it("gives an image and a video their own pages, and goes through the app's router", () => {
    const pushed: string[] = [];
    const nav = webCreationsNav((h) => pushed.push(h));
    nav.make("music");
    expect(pushed).toEqual(["/voice/music"]);
    expect(nav.href?.("video")).toBe("/video");
  });
});
