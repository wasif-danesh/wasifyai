// Helpers for tests that need server-sent events.
export type Evt = [name: string, data: Record<string, unknown>];

export const RUN = "11111111-1111-1111-1111-111111111111";

/** One SSE message as the server writes it. `seq` doubles as the id, as in production. */
export function frame(seq: number, name: string, data: Record<string, unknown> = {}): string {
  const body = { run_id: RUN, thread_id: "t", seq, ts: "", ...data };
  return `id: ${seq}\nevent: ${name}\ndata: ${JSON.stringify(body)}\n\n`;
}

/** A streaming response with the given events, numbered from `from`. */
export function sse(events: Evt[], from = 1, status = 200): Response {
  const text = events.map(([name, data], i) => frame(from + i, name, data)).join("");
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      c.enqueue(new TextEncoder().encode(text));
      c.close();
    },
  });
  return new Response(body, { status, headers: { "content-type": "text/event-stream" } });
}

export const node = (n: string, label = n): Evt => ["node", { node: n, status: "started", label }];
export const token = (text: string): Evt => ["token", { node: "write_lyrics", text }];
export const interrupt = (extra: Record<string, unknown> = {}): Evt => [
  "interrupt",
  {
    interrupt_id: "i",
    kind: "approve_lyrics",
    payload: {
      title: "Rain",
      lyrics: "[verse]\nla",
      style: "pop",
      regenerations_left: 5,
      error: "",
      ...extra,
    },
  },
];
export const done = (outputs: Record<string, unknown> = {}): Evt => [
  "done",
  {
    outputs: {
      status: "done",
      song_id: "s1",
      title: "Rain",
      lyrics: "[verse]\nla",
      style: "pop",
      audio_url: "http://a/x.mp3",
      cover_url: "http://c/x.png",
      ...outputs,
    },
  },
];
