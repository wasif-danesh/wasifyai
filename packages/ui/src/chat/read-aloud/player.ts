// Plays the passages of a reply that is read aloud (ADR-0083, CU3). One audio element is used for the whole reply and it is
// "unlocked" inside the click that starts it, because a browser engine (WebKit, which the Mac window is) lets a page play sound only after
// a click and a later passage, played after the network answered, is no longer inside that click. The sound is held as a blob
// address for as long as it plays and released straight after; nothing is stored.

export type Player = {
  /** called inside the click that starts reading: lets the passages that follow play */
  unlock(): void;
  /** plays one passage; resolves when it has ended (or was stopped), rejects when it cannot be played */
  play(wav: Blob): Promise<void>;
  /** stops what is playing and releases it */
  stop(): void;
};

// 0.1 s of silence, 8 kHz mono 16-bit: the smallest sound that unlocks the element
function silence(): Blob {
  const samples = 800;
  const buf = new ArrayBuffer(44 + samples * 2);
  const v = new DataView(buf);
  const text = (at: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(at + i, s.charCodeAt(i));
  };
  text(0, "RIFF");
  v.setUint32(4, 36 + samples * 2, true);
  text(8, "WAVEfmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, 8000, true);
  v.setUint32(28, 16000, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  text(36, "data");
  v.setUint32(40, samples * 2, true);
  return new Blob([buf], { type: "audio/wav" });
}

export function createPlayer(): Player {
  let audio: HTMLAudioElement | null = null;
  let url: string | null = null;
  let settle: (() => void) | null = null;

  const release = () => {
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      audio.pause();
      audio.removeAttribute("src");
    }
    if (url) URL.revokeObjectURL(url);
    url = null;
  };
  const element = () => {
    audio ??= new Audio();
    return audio;
  };

  return {
    unlock() {
      const a = element();
      url = URL.createObjectURL(silence());
      a.src = url;
      a.volume = 0;
      // the answer is not needed: a refusal here only means the sound is blocked, and the first real passage says so
      void a.play().catch(() => {});
    },
    play(wav) {
      return new Promise<void>((resolve, reject) => {
        const a = element();
        release();
        settle = resolve;
        url = URL.createObjectURL(wav);
        a.src = url;
        a.volume = 1;
        a.onended = () => {
          release();
          settle = null;
          resolve();
        };
        a.onerror = () => {
          release();
          settle = null;
          reject(new Error("The sound could not be played."));
        };
        a.play().catch((e: unknown) => {
          release();
          settle = null;
          reject(
            e instanceof DOMException && e.name === "NotAllowedError"
              ? new Error("This window did not allow sound. Press Read aloud again.")
              : new Error("The sound could not be played."),
          );
        });
      });
    },
    stop() {
      const done = settle;
      settle = null;
      release();
      done?.();
    },
  };
}
