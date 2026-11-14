"use client";
// What the coding screens keep track of: the engine (is it set up), the models, the sessions, and the one
// session that is open with its turns and its stream.
import type {
  CodeAnswer,
  CodeApi,
  CodeCheck,
  CodeEngine,
  CodeEvent,
  CodeMode,
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
  /** the session's checks, the newest first: what a turn from before the app started shows of its check */
  checks: CodeCheck[];
  /** a message was sent and the engine has not answered yet, or Stop was pressed */
  busy: "sending" | "stopping" | null;
  /** it goes up when the project's files may have changed: a turn ended, an undo, a "bring it back" */
  filesTick: number;
  /** what the last undo or "bring it back" said beside doing it (the person's own changes went with it) */
  undoNote: string | null;
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
    checks: [],
    busy: null,
    filesTick: 0,
    undoNote: null,
  });
  const patch = useCallback((p: Partial<CodeState>) => setState((s) => ({ ...s, ...p })), []);
  const openId = state.session?.id ?? null;

  // the session's checks, for the turns whose events are not known; an engine that has none answers nothing
  const checksOf = useCallback(
    async (id: string): Promise<CodeCheck[]> => {
      try {
        return (await api.check(id)).checks;
      } catch {
        return [];
      }
    },
    [api],
  );

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
              const [session, turns, checks] = await Promise.all([
                api.session(openId),
                api.turns(openId),
                checksOf(openId),
              ]);
              if (!gone) {
                setState((s) => ({
                  ...s,
                  session,
                  turns,
                  checks,
                  busy: null,
                  filesTick: s.filesTick + 1,
                }));
              }
            } else if (event.event === "code_state" && event.state === "checking") {
              // the bar says "Checking" while the check runs
              setState((s) =>
                s.session?.id === openId ? { ...s, session: { ...s.session, checking: true } } : s,
              );
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
  }, [api, openId, checksOf]);

  const open = useCallback(
    async (id: string) => {
      try {
        const [session, turns, checks] = await Promise.all([
          api.session(id),
          api.turns(id),
          checksOf(id),
        ]);
        patch({ session, turns, checks, events: [], error: null, busy: null });
      } catch (e) {
        patch({ error: say(e, "That session could not be opened.") });
      }
    },
    [api, patch, checksOf],
  );

  const close = useCallback(() => {
    patch({ session: null, turns: [], events: [], checks: [], busy: null });
    void refresh();
  }, [patch, refresh]);

  const start = useCallback(
    async (folder: string, model?: string, mode: CodeMode = "ask") => {
      try {
        const session = await api.start({ folder, model, mode });
        patch({ session, turns: [], events: [], checks: [], error: null, busy: null });
        return session;
      } catch (e) {
        patch({ error: say(e, "That folder could not be opened.") });
        return null;
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

  const dismiss = useCallback(() => patch({ error: null, undoNote: null }), [patch]);

  const setMode = useCallback(
    async (mode: CodeMode) => {
      if (!openId) return false;
      try {
        patch({ session: await api.setMode(openId, mode), error: null });
        return true;
      } catch (e) {
        patch({ error: say(e, "The mode could not be changed.") });
        return false;
      }
    },
    [api, openId, patch],
  );

  const answer = useCallback(
    async (askId: string, value: CodeAnswer) => {
      if (!openId) return;
      try {
        await api.answer(openId, askId, value);
      } catch (e) {
        patch({ error: say(e, "The answer could not be sent.") });
      }
    },
    [api, openId, patch],
  );

  const putBack = useCallback(
    async (turnId: string, back: boolean) => {
      if (!openId) return;
      try {
        const done = back ? await api.undo(openId, turnId) : await api.redo(openId, turnId);
        const [session, turns] = await Promise.all([api.session(openId), api.turns(openId)]);
        const notes = [...done.notes];
        if (done.own_changes) {
          notes.unshift(
            back
              ? "Files you changed yourself after this turn went back too. “Bring it back” returns them."
              : "Files you changed yourself since the undo were replaced. “Undo this turn” returns them.",
          );
        }
        setState((s) => ({
          ...s,
          session,
          turns,
          error: null,
          undoNote: notes.length ? notes.join(" ") : null,
          filesTick: s.filesTick + 1,
        }));
      } catch (e) {
        patch({ error: say(e, "The files could not be put back.") });
      }
    },
    [api, openId, patch],
  );
  const undo = useCallback((turnId: string) => putBack(turnId, true), [putBack]);
  const redo = useCallback((turnId: string) => putBack(turnId, false), [putBack]);

  /** Read the open session again: its check was changed or tried. */
  const reload = useCallback(async () => {
    if (!openId) return;
    try {
      const [session, checks] = await Promise.all([api.session(openId), checksOf(openId)]);
      setState((s) => (s.session?.id === openId ? { ...s, session, checks } : s));
    } catch {
      // what is shown stays
    }
  }, [api, openId, checksOf]);

  /** Run the project's check now, outside a turn. Its card arrives on the stream. */
  const runCheck = useCallback(async () => {
    if (!openId) return;
    try {
      const out = await api.runCheck(openId);
      patch({ session: out.session, error: null });
    } catch (e) {
      patch({ error: say(e, "The check could not be run.") });
    }
  }, [api, openId, patch]);

  /** Three more rounds: a new turn that tells the agent the check still fails. */
  const tryAgain = useCallback(async () => {
    if (!openId) return;
    patch({ busy: "sending", error: null });
    try {
      const session = await api.tryAgain(openId);
      const turns = await api.turns(openId);
      patch({ session, turns, busy: null });
    } catch (e) {
      patch({ busy: null, error: say(e, "The agent could not be asked again.") });
    }
  }, [api, openId, patch]);

  const setLimit = useCallback(
    async (usd: number) => {
      if (!openId) return;
      try {
        patch({ session: await api.setLimit(openId, usd), error: null });
      } catch (e) {
        patch({ error: say(e, "The limit could not be changed.") });
      }
    },
    [api, openId, patch],
  );

  return {
    state,
    refresh,
    open,
    close,
    start,
    send,
    stop,
    remove,
    dismiss,
    setLimit,
    setMode,
    answer,
    undo,
    redo,
    reload,
    runCheck,
    tryAgain,
  };
}
