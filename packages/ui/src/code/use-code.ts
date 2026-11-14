"use client";
// What the coding screens keep track of: the engine (is it set up), the models, the sessions, and the one
// session that is open with its turns and its stream.
import type {
  CodeApi,
  CodeEngine,
  CodeEvent,
  CodeModel,
  CodeSession,
  CodeTurn,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

const say = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

export type CodeState = {
  engine: CodeEngine | null;
  models: CodeModel[];
  sessions: CodeSession[];
  loading: boolean;
  error: string | null;
  /** the open session */
  session: CodeSession | null;
  turns: CodeTurn[];
  events: CodeEvent[];
  /** a message was sent and the engine has not answered yet, or Stop was pressed */
  busy: "sending" | "stopping" | null;
};

export function useCode(api: CodeApi) {
  const [state, setState] = useState<CodeState>({
    engine: null,
    models: [],
    sessions: [],
    loading: true,
    error: null,
    session: null,
    turns: [],
    events: [],
    busy: null,
  });
  const patch = useCallback((p: Partial<CodeState>) => setState((s) => ({ ...s, ...p })), []);
  const openId = state.session?.id ?? null;

  const refresh = useCallback(async () => {
    try {
      const engine = await api.engine();
      if (!engine.supported || !engine.installed) {
        patch({ engine, loading: false, error: null });
        return;
      }
      const [models, sessions] = await Promise.all([api.models(), api.sessions()]);
      patch({ engine, models, sessions, loading: false, error: null });
    } catch (e) {
      patch({ loading: false, error: say(e, "The coding sessions could not be read.") });
    }
  }, [api, patch]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // the open session's stream: everything kept since the app started, then each new event
  const seen = useRef(0);
  useEffect(() => {
    if (!openId) return;
    const stop = new AbortController();
    let gone = false;
    seen.current = 0;
    void (async () => {
      while (!gone) {
        try {
          for await (const event of api.events(openId, seen.current, stop.signal)) {
            if (gone) return;
            if (event.seq > seen.current) seen.current = event.seq;
            setState((s) =>
              s.session?.id === openId ? { ...s, events: [...s.events, event] } : s,
            );
            if (event.event === "code_state" && event.state === "done") {
              // the turn is closed: its row now says how it ended, and the session what it cost
              const [session, turns] = await Promise.all([api.session(openId), api.turns(openId)]);
              if (!gone) patch({ session, turns, busy: null });
            }
          }
        } catch {
          // the connection dropped: come back and ask for what was missed
        }
        if (!gone) await new Promise((r) => setTimeout(r, 1000));
      }
    })();
    return () => {
      gone = true;
      stop.abort();
    };
  }, [api, openId, patch]);

  const open = useCallback(
    async (id: string) => {
      try {
        const [session, turns] = await Promise.all([api.session(id), api.turns(id)]);
        patch({ session, turns, events: [], error: null, busy: null });
      } catch (e) {
        patch({ error: say(e, "That session could not be opened.") });
      }
    },
    [api, patch],
  );

  const close = useCallback(() => {
    patch({ session: null, turns: [], events: [], busy: null });
    void refresh();
  }, [patch, refresh]);

  const start = useCallback(
    async (folder: string, model?: string) => {
      try {
        const session = await api.start({ folder, model });
        patch({ session, turns: [], events: [], error: null, busy: null });
      } catch (e) {
        patch({ error: say(e, "That folder could not be opened.") });
      }
    },
    [api, patch],
  );

  const send = useCallback(
    async (text: string) => {
      if (!openId) return;
      patch({ busy: "sending", error: null });
      try {
        const session = await api.send(openId, text);
        const turns = await api.turns(openId);
        patch({ session, turns, busy: null });
      } catch (e) {
        patch({ busy: null, error: say(e, "The message could not be sent.") });
      }
    },
    [api, openId, patch],
  );

  const stop = useCallback(async () => {
    if (!openId) return;
    patch({ busy: "stopping" });
    try {
      const session = await api.stop(openId);
      const turns = await api.turns(openId);
      patch({ session, turns, busy: null });
    } catch (e) {
      patch({ busy: null, error: say(e, "The agent could not be stopped.") });
    }
  }, [api, openId, patch]);

  const remove = useCallback(
    async (id: string) => {
      try {
        await api.remove(id);
        await refresh();
      } catch (e) {
        patch({ error: say(e, "That session could not be deleted.") });
      }
    },
    [api, patch, refresh],
  );

  const dismiss = useCallback(() => patch({ error: null }), [patch]);

  return { state, refresh, open, close, start, send, stop, remove, dismiss };
}
