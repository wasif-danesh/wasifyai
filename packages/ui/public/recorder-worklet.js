// The microphone recorder's audio worklet (ADR-0083, decision 5). It runs on the audio thread, averages the input's channels into
// one and hands the samples to the page in blocks; the page turns them into a 16 kHz mono WAV. It is a file served by the app
// itself because the desktop window's content policy (`default-src 'self'`) refuses a worklet made from a blob or a data address.
// The copy in apps/web/public must be identical (a test checks it).
class WasifyaiRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(4096);
    this.filled = 0;
    this.port.onmessage = (event) => {
      if (event.data === "flush") {
        this.send();
        this.port.postMessage("flushed");
      }
    };
  }

  send() {
    if (this.filled === 0) return;
    const out = this.block.slice(0, this.filled);
    this.port.postMessage(out, [out.buffer]);
    this.filled = 0;
  }

  process(inputs) {
    const channels = inputs[0];
    if (!channels || channels.length === 0) return true;
    const frames = channels[0].length;
    for (let i = 0; i < frames; i++) {
      let sum = 0;
      for (let c = 0; c < channels.length; c++) sum += channels[c][i];
      this.block[this.filled++] = sum / channels.length;
      if (this.filled === this.block.length) this.send();
    }
    return true;
  }
}

registerProcessor("wasifyai-recorder", WasifyaiRecorder);
