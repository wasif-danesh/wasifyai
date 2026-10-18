import { describe, expect, it } from "vitest";
import { type Entry, toRow } from "./creations";
import { clipFromVoice, speechFromVoice, trackFromVoice, transcriptFromVoice } from "./voice-cards";

const speech = speechFromVoice({
  id: "s1",
  text: "Hello there",
  voice: "alloy",
  seconds: 1.5,
  created_at: "2026-10-18T00:00:00Z",
  audio_url: "https://files/x.wav",
});

describe("the voice product in My creations", () => {
  it("turns what the voice product keeps into cards", () => {
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

  it("opens the shared voice screens, not the older detail pages", () => {
    const a: Entry = { kind: "speech", id: "s1", createdAt: speech.created_at, speech };
    const row = toRow(a);
    expect(row.href).toBe("/voice/speak");
    expect(row.detail).toBe("alloy");
    const b: Entry = {
      kind: "transcript",
      id: "t1",
      createdAt: speech.created_at,
      transcript: transcriptFromVoice({ id: "t1", title: "Call", created_at: speech.created_at }),
    };
    expect(toRow(b).href).toBe("/voice/transcribe");
  });

  it("shows a track as music and a clip as a lip sync, both opening the voice screens", () => {
    const when = "2026-10-18T00:00:00Z";
    const song = trackFromVoice({
      id: "k1",
      title: "Rainy day",
      description: "soft piano",
      created_at: when,
      audio_url: "a",
    });
    const row = toRow({ kind: "song", id: "k1", createdAt: when, song });
    expect(row).toMatchObject({ kindLabel: "Music", href: "/voice/tracks", detail: "soft piano" });
    const lipsync = clipFromVoice({
      id: "c1",
      title: "Hello",
      script: "Hello there",
      seconds: 3,
      created_at: when,
      video_url: "v",
    });
    expect(lipsync).toMatchObject({ status: "done", text: "Hello there", video_url: "v" });
    expect(toRow({ kind: "lipsync", id: "c1", createdAt: when, lipsync }).href).toBe(
      "/voice/lipsync",
    );
  });
});
