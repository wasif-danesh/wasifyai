import type { SseEvent } from "@wasifyai/contracts";

export type ParsedEvent = { event: SseEvent["event"]; data: SseEvent; id?: string };

/** Parse an SSE byte stream into events. Ignores comment lines (`: ping`). */
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<ParsedEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    let idx = buf.indexOf("\n\n");
    while (idx !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const parsed = parseBlock(block);
      if (parsed) yield parsed;
      idx = buf.indexOf("\n\n");
    }
  }
}

function parseBlock(block: string): ParsedEvent | null {
  let event = "";
  let id: string | undefined;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("id: ")) id = line.slice(4);
    else if (line.startsWith("event: ")) event = line.slice(7);
    else if (line.startsWith("data: ")) data.push(line.slice(6));
  }
  if (!event || data.length === 0) return null;
  const payload = JSON.parse(data.join("\n"));
  return { event: event as SseEvent["event"], data: { ...payload, event } as SseEvent, id };
}
