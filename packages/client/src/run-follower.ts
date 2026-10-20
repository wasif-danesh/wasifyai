// Following a run to its end across broken connections (ADR-0021: the run lives on the engine and its events are kept, so a
// client that lost the stream asks again from the last event it saw). The chat screen used to do this inline; it lives here
// so every screen that follows a run does it the same way.
import { newId } from "./ids";
import type { OnEvent, RunClient } from "./run-client";
import type { ParsedEvent } from "./sse";
import { HttpError } from "./transport";

/** What a screen needs to know of a run to pick it up again: its id (chosen here, before the first event) and how far it got. */
export type RunFollow = {
  runId: string;
  /** the highest event number seen */
  lastSeq: number;
  /** the first stream has been opened (or tried). Set it back to false to open a new first stream, for a run that is resumed. */
  begun: boolean;
  /** a `done`, `error` or `interrupt` arrived: the engine has nothing more to send until the person answers */
  finished: boolean;
};

export function newRunFollow(runId: string = newId()): RunFollow {
  return { runId, lastSeq: 0, begun: false, finished: false };
}

/** How it ended: `finished` (a closing event arrived), `aborted` (the caller stopped), `lost` (the connection did not come back
 * within the budget; the run goes on at the engine and `followRun` can be called again with the same `RunFollow`). */
export type FollowOutcome = "finished" | "aborted" | "lost";

export type FollowOptions = {
  signal: AbortSignal;
  onEvent: OnEvent;
  /** Connection attempts in a row without a new event before giving up. Default 8, about 30 s of outage with the default delays. */
  attempts?: number;
  /** Seconds-in-milliseconds to wait before attempt `n` (1 = the first re-attach). Default 0.8 s, doubling, at most 5 s. */
  delay?: (n: number) => number;
  /** For tests: how to wait. Must resolve when `signal` aborts. */
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  /** For tests: subscribe to "the network is back". Default: the window's `online` event. */
  onOnline?: (cb: () => void) => () => void;
};

const TERMINAL = new Set(["done", "error", "interrupt"]);

/** A short pause before re-attaching after a stream that had been delivering events. */
const RESUME_PAUSE = 300;

const defaultDelay = (n: number) => Math.min(400 * 2 ** n, 5000);

function browserOnline(cb: () => void): () => void {
  if (typeof window === "undefined" || typeof window.addEventListener !== "function")
    return () => {};
  window.addEventListener("online", cb);
  return () => window.removeEventListener("online", cb);
}

function wait(
  ms: number,
  signal: AbortSignal,
  online: (cb: () => void) => () => void,
): Promise<void> {
  return new Promise<void>((resolve) => {
    if (signal.aborted) return resolve();
    let off = () => {};
    const done = () => {
      clearTimeout(t);
      signal.removeEventListener("abort", done);
      off();
      resolve();
    };
    const t = setTimeout(done, ms);
    signal.addEventListener("abort", done, { once: true });
    off = online(done); // the network came back: no reason to wait out the rest
  });
}

/** A failure that another try will not fix: the engine understood the request and said no (a 4xx other than "not there yet"). */
function final(e: unknown): boolean {
  return (
    e instanceof HttpError &&
    e.status >= 400 &&
    e.status < 500 &&
    e.status !== 404 &&
    e.status !== 408 &&
    e.status !== 429
  );
}

/**
 * Follow a run until it ends. `begin` opens the first stream (start the run under `follow.runId`, or resume it) and is used
 * again only while no event has arrived yet (starting under the same id attaches to the same run). After that, a stream that
 * ends early, breaks, or never opens is replaced by `watchRun` from the last event seen, after a pause that grows. A new event
 * counts as progress and starts the count again, so a run that is cut a hundred times still finishes. An error that another
 * try cannot fix (a 4xx) is thrown.
 */
export async function followRun(
  follow: RunFollow,
  begin: (signal: AbortSignal, onEvent: OnEvent) => Promise<void>,
  watch: RunClient["watchRun"],
  opts: FollowOptions,
): Promise<FollowOutcome> {
  const { signal } = opts;
  const attempts = opts.attempts ?? 8;
  const delay = opts.delay ?? defaultDelay;
  const online = opts.onOnline ?? browserOnline;
  const sleep = opts.sleep ?? ((ms, s) => wait(ms, s, online));

  const take = (e: ParsedEvent) => {
    const { seq, run_id: id } = e.data as unknown as { seq?: unknown; run_id?: unknown };
    if (typeof seq === "number") follow.lastSeq = Math.max(follow.lastSeq, seq);
    // an engine that does not take a client's run id names the run itself: from then on that is the id to ask for
    if (typeof id === "string" && id) follow.runId = id;
    if (TERMINAL.has(e.event)) follow.finished = true;
    opts.onEvent(e);
  };

  let attempt = 0; // connection attempts in a row that brought nothing
  let pause = 0; // how long to wait before the next one
  for (;;) {
    if (signal.aborted) return "aborted";
    if (follow.finished) return "finished";
    if (pause > 0) {
      await sleep(pause, signal);
      if (signal.aborted) return "aborted";
    }
    const before = follow.lastSeq;
    try {
      // until an event has come the run may not exist at the engine, so open the first stream again (same id: same run)
      if (!follow.begun || follow.lastSeq === 0) {
        follow.begun = true;
        await begin(signal, take);
      } else await watch(follow.runId, follow.lastSeq, signal, take);
    } catch (e) {
      if (signal.aborted) return "aborted";
      if (final(e)) throw e;
    }
    if (follow.finished) return "finished";
    if (signal.aborted) return "aborted";
    // an event is progress: the count starts again, and the next try follows soon after
    attempt = follow.lastSeq > before ? 0 : attempt + 1;
    if (attempt >= attempts) return "lost";
    pause = attempt === 0 ? RESUME_PAUSE : delay(attempt);
  }
}
