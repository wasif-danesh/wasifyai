"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import type { AssistantApi, ImagesApi, RunClient } from "@wasifyai/client";
import { type ReactNode, useEffect, useMemo, useRef } from "react";
import type { TrackLookup } from "./ToolCard";
import { type ComposerOptionsAvailable, useComposerOptions } from "./composer-options";
import { ReadAloudProvider, useReadAloud } from "./read-aloud/use-read-aloud";
import { DictationBridge, type DictationTarget } from "./thread/DictationBridge";
import { Thread } from "./thread/Thread";
import { textOf } from "./thread/convert";
import { ThreadEnvProvider } from "./thread/env";
import { preloadMarkdown } from "./thread/markdown/Markdown";
import { useChatRuntime } from "./thread/use-chat-runtime";
import { useThreadChat } from "./thread/use-thread-chat";

export type ChatScreenProps = {
  runs: Pick<RunClient, "startRun" | "watchRun"> & Partial<Pick<RunClient, "cancelRun">>;
  assistant: AssistantApi;
  images: ImagesApi;
  /** Reads a track the assistant made, to play it in the chat. */
  tracks?: TrackLookup;
  /** A saved conversation to open; null starts a new chat. */
  conversationId?: string | null;
  /** The turn finished and the conversation has an id and a title. */
  onConversation?: (id: string, title: string) => void;
  /** Shown above the box while the chat is empty (the greeting). */
  hero?: ReactNode;
  /** Suggestions under the box while the chat is empty. */
  examples?: string[];
  /** Setup notices (no model chosen yet, and so on). */
  notices?: ReactNode;
  /** Why sending is not possible right now. The box stays usable for typing. */
  blockedReason?: string | null;
  /** Open a creation in its own screen. */
  onOpenCreation?: (kind: string, id: string) => void;
  /** Take the person to Settings (a search service that fails: add a key there). */
  onOpenSettings?: () => void;
  /** Open a screen of the app by its menu item id (the assistant offers a button; ADR-0071). */
  onOpenScreen?: (screenId: string) => void;
  /** Where a "No language model" error should send the person. */
  onNeedModel?: () => void;
  /** Title bar actions (rename, delete). */
  actions?: ReactNode;
  title?: string;
  /** The model picker, in the title bar (the window's; ADR-0086). */
  model?: ReactNode;
  /** Which options of the box this screen can offer: a Thinking switch only for a model that can think (ADR-0083). */
  composerOptions?: ComposerOptionsAvailable;
};

/**
 * The assistant's chat (ADR-0057, on assistant-ui since ADR-0082): a thread, a box, tool cards, stop, edit and versions. It knows
 * nothing of the desktop or the web; the app supplies the clients, the greeting and the places to go.
 */
export function ChatScreen({
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
  onOpenScreen,
  onNeedModel,
  actions,
  title,
  model,
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
      onOpenScreen,
      thinkingOn: options.thinking,
      onDecide: (approved: boolean, params?: Record<string, unknown>) =>
        void chat.answer(approved, false, params),
      onAutoRun: () => options.setApproval("auto"),
    }),
    [
      images,
      tracks,
      onOpenCreation,
      onOpenSettings,
      onOpenScreen,
      options.thinking,
      options.setApproval,
      chat.answer,
    ],
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
            model={model}
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
