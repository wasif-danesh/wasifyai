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
    onNew: async (m) => {
      await chat.send(textOfContent(m.content as never));
    },
    onCancel: async () => {
      chat.stop();
    },
  });
}
