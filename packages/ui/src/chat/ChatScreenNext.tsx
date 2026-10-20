"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useEffect, useMemo, useRef } from "react";
import type { ChatScreenProps } from "./ChatScreen";
import { useComposerOptions } from "./composer-options";
import { ReadAloudProvider, useReadAloud } from "./read-aloud/use-read-aloud";
import { DictationBridge, type DictationTarget } from "./thread/DictationBridge";
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
  onOpenSettings,
  onNeedModel,
  actions,
  title,
  composerOptions,
}: ChatScreenProps) {
  // the markdown renderer is a separate chunk: fetch it now, while the person is still typing the first message
  useEffect(() => {
    void preloadMarkdown().catch(() => {});
  }, []);
  const dictated: DictationTarget = useRef(null);
  const options = useComposerOptions(conversationId, composerOptions, (text) =>
    dictated.current?.(text),
  );
  const readAloud = useReadAloud(composerOptions?.readAloud);
  const chat = useThreadChat({
    runs,
    api: assistant,
    conversationId,
    onConversation,
    runInput: options.runInput,
    attachedFiles: options.attach.files,
    onSend: options.attach.clear,
  });
  // a file still going up is not sent without: the message waits until it is there
  const runtime = useChatRuntime(chat, {
    blocked: Boolean(blockedReason) || options.attach.busy,
  });
  const { state } = chat;
  const env = useMemo(
    () => ({
      images,
      tracks,
      onOpenCreation,
      onOpenSettings,
      thinkingOn: options.thinking,
      onDecide: (approved: boolean) => void chat.answer(approved),
    }),
    [images, tracks, onOpenCreation, onOpenSettings, options.thinking, chat.answer],
  );
  const last = state.chat.messages[state.chat.messages.length - 1];
  const lastAnswer = last && last.role === "assistant" ? textOf(last) : "";

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <DictationBridge target={dictated} />
      <ReadAloudProvider value={readAloud}>
        <ThreadEnvProvider value={env}>
          <Thread
            empty={state.chat.messages.length === 0 && state.chat.phase === "idle"}
            hero={hero}
            examples={examples}
            notices={
              options.notice ? (
                <>
                  {notices}
                  {options.notice}
                </>
              ) : (
                notices
              )
            }
            blockedReason={blockedReason}
            options={options.bar}
            attach={options.attach}
            actions={actions}
            title={title}
            error={state.chat.error}
            onRetry={chat.retry}
            onNeedModel={onNeedModel}
            working={state.chat.phase === "working"}
            lastAnswer={lastAnswer}
          />
        </ThreadEnvProvider>
      </ReadAloudProvider>
    </AssistantRuntimeProvider>
  );
}
