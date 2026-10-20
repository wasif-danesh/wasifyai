"use client";

import {
  ASSISTANT_PRODUCT,
  type AssistantApi,
  type ChatAction,
  type FollowOptions,
  type RunClient,
  type RunFollow,
  type TreeState,
  followRun,
  initialTree,
  newId,
  newRunFollow,
  treeReducer,
} from "@wasifyai/client";
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

export const CONNECTION_LOST = "connection_lost";

function describe(e: unknown): string {
  return e instanceof Error && e.message
    ? e.message
    : "We couldn't reach the assistant. Check the connection and try again.";
}

export type ThreadChatOptions = {
  runs: Pick<RunClient, "startRun" | "watchRun"> & Partial<Pick<RunClient, "cancelRun">>;
  api: AssistantApi;
  /** Open this conversation when the screen mounts (a saved chat). */
  conversationId?: string | null;
  /** The turn finished: the conversation now has an id and a title (a new chat gets both). */
  onConversation?: (id: string, title: string) => void;
  /** How long a lost connection is tried again (for tests; the defaults are meant for people). */
  reconnect?: Pick<FollowOptions, "attempts" | "delay">;
};

type Turn = { follow: RunFollow; input: Record<string, unknown>; text: string };

/**
 * One chat for the new thread (ADR-0082): the state is the message tree of `@wasifyai/client`, the engine's events are
 * folded into it, and a run is followed to its end across broken connections (`followRun`). It knows nothing of
 * assistant-ui; `use-chat-runtime.ts` hands this state to the library.
 */
export function useThreadChat({
  runs,
  api,
  conversationId,
  onConversation,
  reconnect,
}: ThreadChatOptions) {
  const [state, dispatchRaw] = useReducer(treeReducer, initialTree);
  const local = useRef(state);
  const abort = useRef<AbortController | null>(null);
  const turn = useRef<Turn | null>(null);
  const notify = useRef(onConversation);
  notify.current = onConversation;
  // the clients are read when a turn runs, not when the hook renders, so a new object each render is harmless
  const clients = useRef({ runs, api });
  clients.current = { runs, api };
  const pacing = useRef(reconnect);
  pacing.current = reconnect;

  const dispatch = useCallback((action: Parameters<typeof treeReducer>[1]) => {
    local.current = treeReducer(local.current, action);
    dispatchRaw(action);
  }, []);
  const chat = useCallback((action: ChatAction) => dispatch({ type: "chat", action }), [dispatch]);

  const drive = useCallback(
    async (t: Turn) => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      const { runs: r } = clients.current;
      try {
        const outcome = await followRun(
          t.follow,
          (signal, onEvent) =>
            r.startRun(ASSISTANT_PRODUCT, t.input, signal, onEvent, t.follow.runId),
          r.watchRun,
          {
            ...pacing.current,
            signal: ctrl.signal,
            onEvent: (event) => {
              dispatch({ type: "event", event });
              if (event.event === "done") {
                const s = local.current.chat;
                if (s.phase === "idle" && s.conversationId)
                  notify.current?.(s.conversationId, s.title);
              }
            },
          },
        );
        if (outcome === "lost")
          chat({
            type: "failed",
            code: CONNECTION_LOST,
            message: "We lost the connection to the assistant. Try again.",
          });
      } catch (e) {
        if (ctrl.signal.aborted) return;
        chat({ type: "failed", message: describe(e) });
      }
    },
    [chat, dispatch],
  );

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || local.current.chat.phase === "working") return;
      const userId = newId();
      const replyId = newId();
      const input: Record<string, unknown> = {
        text: message,
        client_message_id: userId,
        client_reply_id: replyId,
      };
      const conversation = local.current.chat.conversationId;
      if (conversation) input.conversation_id = conversation;
      const t: Turn = { follow: newRunFollow(), input, text: message };
      turn.current = t;
      dispatch({
        type: "begin",
        user: { id: userId, role: "user", parts: [{ type: "text", text: message }] },
        replyId,
        parentId: local.current.headId,
      });
      await drive(t);
    },
    [dispatch, drive],
  );

  const stop = useCallback(() => {
    abort.current?.abort();
    chat({ type: "stopped" });
    // the engine keeps a run going unless it is told to stop; the run id is ours from the start
    const t = turn.current;
    if (t && !t.follow.finished)
      void clients.current.runs.cancelRun?.(t.follow.runId)?.catch(() => {});
  }, [chat]);

  const retry = useCallback(() => {
    const t = turn.current;
    if (!t) return;
    const lost = local.current.chat.error?.code === CONNECTION_LOST && !t.follow.finished;
    if (lost) {
      // the run went on at the engine: pick it up where it was instead of sending the message again
      chat({ type: "resumed" });
      void drive(t);
    } else void send(t.text);
  }, [chat, drive, send]);

  const reset = useCallback(() => {
    abort.current?.abort();
    turn.current = null;
    dispatch({ type: "reset" });
  }, [dispatch]);

  // the network is back after a give-up: pick the run up again without asking
  const lost = state.chat.error?.code === CONNECTION_LOST;
  useEffect(() => {
    if (!lost || typeof window === "undefined") return;
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [lost, retry]);

  // open a saved conversation (and a different one when the id changes)
  useEffect(() => {
    if (!conversationId || conversationId === local.current.chat.conversationId) return;
    let gone = false;
    clients.current.api
      .get(conversationId)
      .then((c) => !gone && dispatch({ type: "loaded", conversation: c }))
      .catch((e) => !gone && chat({ type: "failed", message: describe(e), retryable: false }));
    return () => {
      gone = true;
    };
  }, [conversationId, chat, dispatch]);

  useEffect(() => () => abort.current?.abort(), []);

  return useMemo(
    () => ({ state: state as TreeState, send, stop, retry, reset }),
    [state, send, stop, retry, reset],
  );
}

export type ThreadChat = ReturnType<typeof useThreadChat>;
