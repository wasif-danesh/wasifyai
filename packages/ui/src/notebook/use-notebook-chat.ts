"use client";

import {
  NOTEBOOKS_PRODUCT,
  type NotebooksApi,
  type ParsedEvent,
  type RunClient,
  askReducer,
  initialAsk,
  isWorking,
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
    : "We couldn't reach the notebook. Check the connection and try again.";
}

export type UseNotebookChatOptions = {
  runs: Pick<RunClient, "startRun" | "watchRun">;
  api: NotebooksApi;
  notebookId: string | null;
  /** Open this conversation (a saved one); null is a new conversation. */
  conversationId?: string | null;
  /** The turn finished: the conversation has an id and a title. */
  onConversation?: (id: string, title: string) => void;
};

/**
 * One conversation with a notebook: send a question (optionally to the ticked sources only), follow
 * the run's events into the state, stop, retry, and open a saved conversation. A broken connection
 * re-attaches to the run, as the assistant's chat does.
 */
export function useNotebookChat({
  runs,
  api,
  notebookId,
  conversationId,
  onConversation,
}: UseNotebookChatOptions) {
  const [state, dispatchRaw] = useReducer(askReducer, initialAsk);
  const local = useRef(state);
  const abort = useRef<AbortController | null>(null);
  const last = useRef<{ text: string; documentIds?: string[] } | null>(null);
  const notify = useRef(onConversation);
  notify.current = onConversation;

  const dispatch = useCallback((action: Parameters<typeof askReducer>[1]) => {
    local.current = askReducer(local.current, action);
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
    async (text: string, documentIds?: string[]) => {
      const message = text.trim();
      if (!message || !notebookId || isWorking(local.current)) return;
      last.current = { text: message, documentIds };
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      dispatch({ type: "submitted", text: message, id: `u-${Date.now()}` });
      const input: Record<string, unknown> = { text: message, notebook_id: notebookId };
      if (local.current.conversationId) input.conversation_id = local.current.conversationId;
      if (documentIds !== undefined) input.document_ids = documentIds;
      const resting = () => !isWorking(local.current);
      try {
        await runs.startRun(NOTEBOOKS_PRODUCT, input, ctrl.signal, onEvent);
        let attempt = 0;
        while (!ctrl.signal.aborted && !resting()) {
          const runId = local.current.runId;
          if (!runId || attempt >= MAX_RECONNECTS) {
            dispatch({
              type: "failed",
              message: "We lost the connection to the notebook. Try again.",
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
    [dispatch, notebookId, onEvent, runs],
  );

  const stop = useCallback(() => {
    abort.current?.abort();
    dispatch({ type: "stopped" });
  }, [dispatch]);

  const retry = useCallback(() => {
    if (last.current) void send(last.current.text, last.current.documentIds);
  }, [send]);

  const reset = useCallback(() => {
    abort.current?.abort();
    dispatch({ type: "reset" });
  }, [dispatch]);

  // open a saved conversation (and a different one when the id changes)
  useEffect(() => {
    if (!notebookId || !conversationId || conversationId === local.current.conversationId) return;
    let gone = false;
    api
      .conversation(notebookId, conversationId)
      .then((c) => !gone && dispatch({ type: "loaded", conversation: c }))
      .catch((e) => !gone && dispatch({ type: "failed", message: describe(e), retryable: false }));
    return () => {
      gone = true;
    };
  }, [notebookId, conversationId, api, dispatch]);

  useEffect(() => () => abort.current?.abort(), []);

  return { state, send, stop, retry, reset };
}
