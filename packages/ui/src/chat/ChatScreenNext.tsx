"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useEffect, useMemo } from "react";
import type { ChatScreenProps } from "./ChatScreen";
import { Thread } from "./thread/Thread";
import { textOf } from "./thread/convert";
import { ThreadEnvProvider } from "./thread/env";
import { preloadMarkdown } from "./thread/markdown/Markdown";
import { useChatRuntime } from "./thread/use-chat-runtime";
import { useThreadChat } from "./thread/use-thread-chat";

/**
 * The assistant's chat on assistant-ui (ADR-0082), with the props of `ChatScreen`: the same screen in a different engine, behind
 * the Labs switch until it has parity. It knows nothing of the desktop or the web; the app supplies the clients, the greeting and
 * the places to go.
 */
export function ChatScreenNext({
  runs,
  assistant,
  images,
  tracks,
  conversationId,
  onConversation,
  hero,
  examples,
  notices,
  blockedReason,
  onOpenCreation,
  onNeedModel,
  actions,
  title,
}: ChatScreenProps) {
  // the markdown renderer is a separate chunk: fetch it now, while the person is still typing the first message
  useEffect(() => {
    void preloadMarkdown().catch(() => {});
  }, []);
  const chat = useThreadChat({ runs, api: assistant, conversationId, onConversation });
  const runtime = useChatRuntime(chat, { blocked: Boolean(blockedReason) });
  const { state } = chat;
  const env = useMemo(() => ({ images, tracks, onOpenCreation }), [images, tracks, onOpenCreation]);
  const last = state.chat.messages[state.chat.messages.length - 1];
  const lastAnswer = last && last.role === "assistant" ? textOf(last) : "";

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadEnvProvider value={env}>
        <Thread
          empty={state.chat.messages.length === 0 && state.chat.phase === "idle"}
          hero={hero}
          examples={examples}
          notices={notices}
          blockedReason={blockedReason}
          actions={actions}
          title={title}
          error={state.chat.error}
          onRetry={chat.retry}
          onNeedModel={onNeedModel}
          working={state.chat.phase === "working"}
          lastAnswer={lastAnswer}
        />
      </ThreadEnvProvider>
    </AssistantRuntimeProvider>
  );
}
