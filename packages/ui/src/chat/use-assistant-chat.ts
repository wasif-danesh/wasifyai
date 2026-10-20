"use client";

import {
  ASSISTANT_PRODUCT,
  type AssistantApi,
  type ParsedEvent,
  type RunClient,
  chatReducer,
  initialChat,
} from "@wasifyai/client";
import { useCallback, useEffect, useReducer, useRef } from "react";

const MAX_RECONNECTS = 3;

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        resolve();
      },
      { once: true },
    );
  });

function describe(e: unknown): string {
  return e instanceof Error && e.message
    ? e.message
    : "We couldn't reach the assistant. Check the connection and try again.";
}

export type UseAssistantChatOptions = {
  runs: Pick<RunClient, "startRun" | "watchRun">;
  api: AssistantApi;
  /** Open this conversation when the screen mounts (a saved chat). */
  conversationId?: string | null;
  /** The turn finished: the conversation now has an id and a title (a new chat gets both). */
  onConversation?: (id: string, title: string) => void;
  /** Extra fields for the next run's input (the options of the box: `{ thinking: true }`). */
  runInput?: Record<string, unknown>;
};

/**
 * One chat: send a message, follow the run's events into the screen's state, stop, retry, and open a
 * saved conversation. A broken connection re-attaches to the run (the server replays what was missed).
 */
export function useAssistantChat({
  runs,
  api,
  conversationId,
  onConversation,
  runInput,
}: UseAssistantChatOptions) {
  const [state, dispatchRaw] = useReducer(chatReducer, initialChat);
  const local = useRef(state);
  const abort = useRef<AbortController | null>(null);
  const lastText = useRef("");
  const notify = useRef(onConversation);
  notify.current = onConversation;
  const extra = useRef(runInput);
  extra.current = runInput;

  const dispatch = useCallback((action: Parameters<typeof chatReducer>[1]) => {
    local.current = chatReducer(local.current, action);
    dispatchRaw(action);
  }, []);

  const onEvent = useCallback(
    (event: ParsedEvent) => {
      dispatch({ type: "event", event });
      if (event.event === "done") {
        const s = local.current;
        if (s.phase === "idle" && s.conversationId) notify.current?.(s.conversationId, s.title);
      }
    },
    [dispatch],
  );

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || local.current.phase === "working") return;
      lastText.current = message;
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      dispatch({ type: "submitted", text: message, id: `u-${Date.now()}` });
      const input: Record<string, unknown> = { ...extra.current, text: message };
      if (local.current.conversationId) input.conversation_id = local.current.conversationId;
      const resting = () => local.current.phase !== "working";
      try {
        await runs.startRun(ASSISTANT_PRODUCT, input, ctrl.signal, onEvent);
        let attempt = 0;
        while (!ctrl.signal.aborted && !resting()) {
          const runId = local.current.runId;
          if (!runId || attempt >= MAX_RECONNECTS) {
            dispatch({
              type: "failed",
              message: "We lost the connection to the assistant. Try again.",
            });
            return;
          }
          attempt += 1;
          await sleep(Math.min(400 * 2 ** attempt, 3000), ctrl.signal);
          if (ctrl.signal.aborted) return;
          await runs.watchRun(runId, local.current.lastSeq, ctrl.signal, onEvent).catch(() => {});
        }
      } catch (e) {
        if (ctrl.signal.aborted) return;
        // a broken stream after the run began is worth re-attaching to
        const runId = local.current.runId;
        if (runId && !resting()) {
          try {
            await runs.watchRun(runId, local.current.lastSeq, ctrl.signal, onEvent);
            if (resting()) return;
          } catch {
            // fall through to the message below
          }
        }
        dispatch({ type: "failed", message: describe(e) });
      }
    },
    [dispatch, onEvent, runs],
  );

  const stop = useCallback(() => {
    abort.current?.abort();
    dispatch({ type: "stopped" });
  }, [dispatch]);

  const retry = useCallback(() => {
    if (lastText.current) void send(lastText.current);
  }, [send]);

  const reset = useCallback(() => {
    abort.current?.abort();
    dispatch({ type: "reset" });
  }, [dispatch]);

  // open a saved conversation (and a different one when the id changes)
  useEffect(() => {
    if (!conversationId || conversationId === local.current.conversationId) return;
    let gone = false;
    api
      .get(conversationId)
      .then((c) => !gone && dispatch({ type: "loaded", conversation: c }))
      .catch((e) => !gone && dispatch({ type: "failed", message: describe(e), retryable: false }));
    return () => {
      gone = true;
    };
  }, [conversationId, api, dispatch]);

  useEffect(() => () => abort.current?.abort(), []);

  return { state, send, stop, retry, reset };
}
