"use client";

import {
  ASSISTANT_PRODUCT,
  type AssistantApi,
  type AttachmentInfo,
  type ChatAction,
  type ChatPart,
  type ConfirmAnswer,
  type FollowOptions,
  type OnEvent,
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
  runs: Pick<RunClient, "startRun" | "watchRun"> &
    Partial<Pick<RunClient, "cancelRun" | "resumeRun">>;
  api: AssistantApi;
  /** Open this conversation when the screen mounts (a saved chat). */
  conversationId?: string | null;
  /** The turn finished: the conversation now has an id and a title (a new chat gets both). */
  onConversation?: (id: string, title: string) => void;
  /** Extra fields for the next run's input (the options of the box: `{ thinking: true }`). */
  runInput?: Record<string, unknown>;
  /** The files attached to the next message, as the message shows them (their ids go in `runInput`). */
  attachedFiles?: AttachmentInfo[];
  /** A message was sent: what was attached to it belongs to it now, and the box lets go. */
  onSend?: () => void;
  /** How long a lost connection is tried again (for tests; the defaults are meant for people). */
  reconnect?: Pick<FollowOptions, "attempts" | "delay">;
};

/** One run: what it sent, how to follow it, and how to do it again (Try again after a failure). */
type Turn = { follow: RunFollow; input: Record<string, unknown>; again: () => Promise<void> };

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
  runInput,
  attachedFiles,
  onSend,
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
  const extra = useRef(runInput);
  extra.current = runInput;
  const files = useRef(attachedFiles);
  files.current = attachedFiles;
  const sent = useRef(onSend);
  sent.current = onSend;
  const pacing = useRef(reconnect);
  pacing.current = reconnect;

  const dispatch = useCallback((action: Parameters<typeof treeReducer>[1]) => {
    local.current = treeReducer(local.current, action);
    dispatchRaw(action);
  }, []);
  const chat = useCallback((action: ChatAction) => dispatch({ type: "chat", action }), [dispatch]);

  const drive = useCallback(
    async (t: Turn, begin?: (signal: AbortSignal, onEvent: OnEvent) => Promise<void>) => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      const { runs: r } = clients.current;
      try {
        const outcome = await followRun(
          t.follow,
          begin ??
            ((signal, onEvent) =>
              r.startRun(ASSISTANT_PRODUCT, t.input, signal, onEvent, t.follow.runId)),
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

  /**
   * Answer the card that waits on the branch on screen, and follow the turn on to its end. `expired` is the person going on
   * without answering: the engine closes the turn without another model call.
   */
  const answer = useCallback(
    async (approved: boolean, expired = false) => {
      const runId = local.current.pendingRunId;
      const resume = clients.current.runs.resumeRun;
      if (!runId || !resume) return;
      const value: ConfirmAnswer = expired ? { approved: false, expired: true } : { approved };
      dispatch({ type: "answered", approved });
      // the parked run is followed on from where it stopped (a card read from a saved chat starts at the beginning)
      const follow = newRunFollow(runId);
      follow.lastSeq = local.current.chat.lastSeq;
      const t: Turn = { follow, input: {}, again: async () => {} };
      turn.current = t;
      await drive(t, (signal, onEvent) => resume(runId, value, signal, onEvent));
    },
    [dispatch, drive],
  );

  /** A card is waiting and the person moves on: close it first, so the turn is whole before the next one starts. */
  const closeCard = useCallback(async () => {
    if (local.current.pendingRunId) await answer(false, true);
  }, [answer]);

  /**
   * Send a message under `parentId` (a node: the end of the branch on screen unless told otherwise; null for a first message).
   * Editing a message is sending its new text under the old one's parent: the old one stays as a sibling.
   */
  const send = useCallback(
    async (text: string, opts: { parentId?: string | null } = {}) => {
      const message = text.trim();
      // a file with no words is a message too (the engine names the chat after the file)
      if ((!message && !files.current?.length) || local.current.chat.phase === "working") return;
      await closeCard();
      const parentId = opts.parentId === undefined ? local.current.headId : opts.parentId;
      const userId = newId();
      const replyId = newId();
      const input: Record<string, unknown> = {
        ...extra.current,
        approvals: true, // this screen shows the card and sends the answer back
        text: message,
        client_message_id: userId,
        client_reply_id: replyId,
        parent_message_id: parentId ?? "",
      };
      const conversation = local.current.chat.conversationId;
      if (conversation) input.conversation_id = conversation;
      const t: Turn = {
        follow: newRunFollow(),
        input,
        again: () => send(message, { parentId: opts.parentId }),
      };
      turn.current = t;
      dispatch({
        type: "begin",
        user: {
          id: userId,
          role: "user",
          parts: [
            { type: "text", text: message },
            ...(files.current ?? []).map((file): ChatPart => ({ type: "attachment", file })),
          ],
        },
        replyId,
        parentId,
      });
      sent.current?.(); // the files belong to this message now
      await drive(t);
    },
    [dispatch, drive, closeCard],
  );

  /** Answer the message `userId` again: the new answer is a sibling of the old one, and nothing is asked twice. */
  const regenerate = useCallback(
    async (userId: string) => {
      const conversation = local.current.chat.conversationId;
      const node = local.current.nodes[userId];
      if (!conversation || !node || node.message.role !== "user") return;
      if (local.current.chat.phase === "working") return;
      await closeCard();
      const replyId = newId();
      const input: Record<string, unknown> = {
        ...extra.current,
        approvals: true,
        conversation_id: conversation,
        parent_message_id: userId,
        regenerate: true,
        client_reply_id: replyId,
      };
      const t: Turn = {
        follow: newRunFollow(),
        input,
        again: () => regenerate(userId),
      };
      turn.current = t;
      dispatch({ type: "begin", user: null, replyId, parentId: userId });
      await drive(t);
    },
    [dispatch, drive, closeCard],
  );

  /** Show another branch, and remember it at the engine so a reload comes back to it. */
  const selectBranch = useCallback(
    (nodeId: string) => {
      dispatch({ type: "head", headId: nodeId });
      const { chat: c, headId } = local.current;
      if (c.conversationId && headId)
        void clients.current.api.setHead(c.conversationId, headId).catch(() => {});
    },
    [dispatch],
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
    } else void t.again();
  }, [chat, drive]);

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
      .get(conversationId, { tree: true })
      .then((c) => !gone && dispatch({ type: "loaded", conversation: c }))
      .catch((e) => !gone && chat({ type: "failed", message: describe(e), retryable: false }));
    return () => {
      gone = true;
    };
  }, [conversationId, chat, dispatch]);

  useEffect(() => () => abort.current?.abort(), []);

  return useMemo(
    () => ({
      state: state as TreeState,
      send,
      regenerate,
      selectBranch,
      answer,
      stop,
      retry,
      reset,
    }),
    [state, send, regenerate, selectBranch, answer, stop, retry, reset],
  );
}

export type ThreadChat = ReturnType<typeof useThreadChat>;
