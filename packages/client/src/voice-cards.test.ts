import { describe, expect, it } from "vitest";
import { clipFromVoice, speechFromVoice, trackFromVoice, transcriptFromVoice } from "./voice-cards";

describe("the voice product in My creations", () => {
  it("turns what the voice product keeps into cards", () => {
    const speech = speechFromVoice({
      id: "s1",
      text: "Hello there",
      voice: "alloy",
      seconds: 1.5,
      created_at: "2026-10-18T00:00:00Z",
      audio_url: "https://files/x.wav",
    });
    expect(speech).toMatchObject({ id: "s1", voice: "alloy", seconds: 1.5 });
    const t = transcriptFromVoice({
      id: "t1",
      title: "Call",
      text: "x".repeat(400),
      seconds: 12,
      created_at: "2026-10-18T00:00:00Z",
    });
    expect(t.preview).toHaveLength(240);
    expect(t.status).toBe("done");
  });

  it("shows a track as music and a clip as a lip sync", () => {
    const when = "2026-10-18T00:00:00Z";
    const song = trackFromVoice({
      id: "k1",
      title: "Rainy day",
      description: "soft piano",
      created_at: when,
      audio_url: "a",
    });
    expect(song).toMatchObject({ title: "Rainy day", style: "soft piano" });
    const lipsync = clipFromVoice({
      id: "c1",
      title: "Hello",
      script: "Hello there",
      seconds: 3,
      created_at: when,
      video_url: "v",
    });
    expect(lipsync).toMatchObject({ status: "done", text: "Hello there", video_url: "v" });
  });
});
