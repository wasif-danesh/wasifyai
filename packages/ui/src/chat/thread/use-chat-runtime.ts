"use client";
// The ONLY file of ours that imports assistant-ui's runtime API (ADR-0082: the library is 0.x and moves, so an upgrade
// lands here). It hands our message tree to the library as an `ExternalStoreRuntime`: our state is the only copy of the
// conversation, and the library's callbacks call our hook.
import {
  type ExportedMessageRepository,
  type ThreadMessage,
  type ThreadMessageLike,
  fromThreadMessageLike,
  useExternalStoreRuntime,
} from "@assistant-ui/react";
import type { ChatMessage } from "@wasifyai/client";
import { useMemo, useRef } from "react";
import { toLikeMessage } from "./convert";
import type { ThreadChat } from "./use-thread-chat";

const textOfContent = (content: readonly { type: string; text?: string }[]) =>
  content.map((c) => (c.type === "text" ? (c.text ?? "") : "")).join("");

export function useChatRuntime(chat: ThreadChat, opts: { blocked?: boolean } = {}) {
  const { state } = chat;
  // one ThreadMessage per ChatMessage object: a message that did not change keeps its identity between tokens
  const cache = useRef(new WeakMap<ChatMessage, ThreadMessage>());
  const repository = useMemo(() => {
    const items = state.order.flatMap((id) => {
      const node = state.nodes[id];
      if (!node) return [];
      let message = cache.current.get(node.message);
      if (!message) {
        const like = toLikeMessage(node.message) as unknown as ThreadMessageLike;
        message = fromThreadMessageLike(
          like,
          node.id,
          (like.status ?? { type: "complete", reason: "unknown" }) as never,
        );
        cache.current.set(node.message, message);
      }
      return [{ message, parentId: node.parentId }];
    });
    return { headId: state.headId, messages: items } as ExportedMessageRepository;
  }, [state.nodes, state.order, state.headId]);

  return useExternalStoreRuntime<ThreadMessage>({
    isRunning: state.chat.phase === "working",
    // sending is blocked (no model chosen yet) but the box stays usable for typing; Enter obeys this too
    isSendDisabled: Boolean(opts.blocked),
    messageRepository: repository,
    // a handler for `setMessages` is what switches branch switching on in the library; our state is the only copy, so it does nothing
    setMessages: () => {},
    // the person picked another version: our state follows, and the engine is told so a reload comes back to it
    unstable_onBranchChange: ({ headId }) => {
      if (headId) chat.selectBranch(headId);
    },
    onNew: async (m) => {
      await chat.send(textOfContent(m.content as never), { parentId: m.parentId });
    },
    // an edit is a new message under the old one's parent: the old one stays as another version
    onEdit: async (m) => {
      await chat.send(textOfContent(m.content as never), { parentId: m.parentId });
    },
    // "answer again": `parentId` is the message being answered
    onReload: async (parentId) => {
      if (parentId) await chat.regenerate(parentId);
    },
    onCancel: async () => {
      chat.stop();
    },
  });
}

/**
 * The same runtime for a plain back-and-forth that is not a tree (the notebook chat, stage CU4): each message follows the one before,
 * there is no edit, no "answer again" and no versions, only send, Stop and the messages themselves.
 */
export function useLinearRuntime(opts: {
  messages: ChatMessage[];
  running: boolean;
  blocked?: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const { messages, running, blocked, onSend, onStop } = opts;
  const cache = useRef(new WeakMap<ChatMessage, ThreadMessage>());
  const repository = useMemo(() => {
    const items = messages.map((m, i) => {
      let message = cache.current.get(m);
      if (!message) {
        const like = toLikeMessage(m) as unknown as ThreadMessageLike;
        message = fromThreadMessageLike(
          like,
          m.id,
          (like.status ?? { type: "complete", reason: "unknown" }) as never,
        );
        cache.current.set(m, message);
      }
      return { message, parentId: messages[i - 1]?.id ?? null };
    });
    return {
      headId: messages[messages.length - 1]?.id ?? null,
      messages: items,
    } as ExportedMessageRepository;
  }, [messages]);

  return useExternalStoreRuntime<ThreadMessage>({
    isRunning: running,
    isSendDisabled: Boolean(blocked),
    messageRepository: repository,
    onNew: async (m) => {
      onSend(textOfContent(m.content as never));
    },
    onCancel: async () => {
      onStop();
    },
  });
}
