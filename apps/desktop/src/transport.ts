// SPDX-License-Identifier: AGPL-3.0-only
import type { Transport } from "@wasifyai/client";
import type { EngineSession } from "./engine";

/** Ask for a new token this long before the current one runs out. */
const REFRESH_BEFORE_MS = 60_000;

export type EngineTransport = Transport & {
  /** Forget the token: the engine was restarted and has a new address and secret. */
  invalidate(): void;
  /** The engine's address, for what cannot go through `fetch` (the preview's frame). */
  base(): Promise<string>;
};

/**
 * How the desktop window reaches the engine: its loopback address, with the token the shell signs for
 * it. The token is asked for when needed and kept until shortly before it expires; a 401 (the engine
 * restarted with a new secret) asks once more and retries the call.
 */
export function createEngineTransport(
  getSession: () => Promise<EngineSession>,
  options: { now?: () => number; fetch?: typeof fetch } = {},
): EngineTransport {
  const now = options.now ?? Date.now;
  const doFetch = options.fetch ?? ((url, init) => fetch(url, init));
  let session: EngineSession | null = null;
  let pending: Promise<EngineSession> | null = null;

  function current(): Promise<EngineSession> {
    if (session && session.expires_at * 1000 - now() > REFRESH_BEFORE_MS) {
      return Promise.resolve(session);
    }
    // one asker at a time: several calls at once share the answer
    pending ??= getSession()
      .then((s) => {
        session = s;
        return s;
      })
      .finally(() => {
        pending = null;
      });
    return pending;
  }

  function send(s: EngineSession, path: string, init?: RequestInit): Promise<Response> {
    const headers = new Headers(init?.headers);
    headers.set("authorization", `Bearer ${s.token}`);
    return doFetch(`${s.base_url}${path}`, { ...init, headers });
  }

  return {
    invalidate() {
      session = null;
    },
    async base() {
      return (await current()).base_url;
    },
    async fetch(path, init) {
      const res = await send(await current(), path, init);
      if (res.status !== 401) return res;
      session = null; // the engine did not accept it: ask the shell for a fresh one, once
      return send(await current(), path, init);
    },
  };
}
