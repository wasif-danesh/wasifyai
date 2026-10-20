// From the microphone's samples to what the speech runtime reads: 16 kHz, one channel, 16-bit PCM in a WAV (ADR-0083). No library: the
// window does it, so the engine never converts anything and the clip is the same on every computer.

export const SPEECH_RATE = 16000;

/** The samples, joined and averaged down to `SPEECH_RATE`: each output sample is the mean of the input samples it covers. */
export function toSpeechRate(blocks: Float32Array[], inputRate: number): Float32Array {
  let total = 0;
  for (const b of blocks) total += b.length;
  const ratio = inputRate / SPEECH_RATE;
  const out = new Float32Array(Math.floor(total / ratio));
  if (out.length === 0) return out;
  const flat = new Float32Array(total);
  let at = 0;
  for (const b of blocks) {
    flat.set(b, at);
    at += b.length;
  }
  if (ratio === 1) return flat;
  for (let j = 0; j < out.length; j++) {
    const from = Math.floor(j * ratio);
    const to = Math.min(total, Math.max(from + 1, Math.floor((j + 1) * ratio)));
    let sum = 0;
    for (let i = from; i < to; i++) sum += flat[i] ?? 0;
    out[j] = sum / (to - from);
  }
  return out;
}

/** A 16-bit PCM WAV of mono samples at `SPEECH_RATE` (values outside -1 to 1 are cut). */
export function encodeWav(samples: Float32Array): Blob {
  const bytes = samples.length * 2;
  const buf = new ArrayBuffer(44 + bytes);
  const v = new DataView(buf);
  const text = (at: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(at + i, s.charCodeAt(i));
  };
  text(0, "RIFF");
  v.setUint32(4, 36 + bytes, true);
  text(8, "WAVE");
  text(12, "fmt ");
  v.setUint32(16, 16, true); // the format chunk is 16 bytes
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // one channel
  v.setUint32(24, SPEECH_RATE, true);
  v.setUint32(28, SPEECH_RATE * 2, true); // bytes a second
  v.setUint16(32, 2, true); // bytes a frame
  v.setUint16(34, 16, true);
  text(36, "data");
  v.setUint32(40, bytes, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i] ?? 0));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

/** The loudest sample, 0 to 1: a clip below about 0.004 has nothing in it. */
export function peakOf(samples: Float32Array): number {
  let peak = 0;
  for (const s of samples) peak = Math.max(peak, Math.abs(s));
  return peak;
}
